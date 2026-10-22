"""JSON API аккаунта: регистрация, вход и «сохранение» прогресса.

Сохранение — один JSON-документ на аккаунт (профиль и агрегированный прогресс) с полем
`updated` (мс, по часам телефона):

    {"v": 2, "updated": 1760500000000,
     "profile": {"name": "Аня", "avatar": "🦊"},
     "words": {"17": {"ok": 3, "bad": 1, "seen": 2, "streak": 2, "last": 1760500000000}},
     "days": {"2026-10-15": {"ok": 12, "bad": 3, "seen": 5}},
     "games": {"choose": {"ok": 20, "bad": 4, "played": 3, "best": 3}},
     "settings": {"sound": true, "notifications": false, "geo": false}}

`streak` — верные ответы на слово подряд (после ошибки — 0): после трёх подряд слово
перестаёт быть «трудным» (режим «Трудные слова», `ZB.hardWords` в static/js/app.js). В старых
сохранениях поля нет, клиент считает его нулём.

`settings` — настройки игрока (звук, напоминание, геолокация), едут вместе с прогрессом на
любой телефон. Только булевы ключи из SETTINGS_DEFAULTS: неизвестные отбрасываются, не булевы
значения и отсутствующие ключи заменяются значениями по умолчанию. В сохранениях, записанных до
появления блока, его нет — тогда подставляются значения по умолчанию (`clean_settings`).

При синхронизации более новое сохранение заменяет старое целиком, без слияния. Сервер
принимает PUT, только если присланное не старее хранимого, иначе отвечает 409 и своим
сохранением — так два устройства не затирают друг друга в гонке.

Авторизация — токен в заголовке `Authorization: Bearer …` (подписанный id пользователя),
без cookies, поэтому CSRF здесь не нужен.

Вход и регистрация ограничены по частоте (`rate_limit`), чтобы пароль нельзя было подбирать
перебором, а аккаунты — создавать скриптом.
"""

import json
from functools import wraps

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import Profile

TOKEN_SALT = "votes.api"
SAVE_VERSION = 2
MAX_SAVE_BYTES = 256 * 1024
SAVE_SECTIONS = ("words", "days", "games")
SETTINGS_DEFAULTS = {"sound": True, "notifications": False, "geo": False}
USERNAME_MAX = 150  # как у поля username в модели User
PASSWORD_MIN = 6  # как в AUTH_PASSWORD_VALIDATORS
NAME_MAX = 60
AVATAR_MAX = 16  # эмодзи бывает из нескольких символов, запас с избытком
BEARER = "Bearer "


def make_token(user) -> str:
    """Токен = id пользователя, подписанный SECRET_KEY. Срока действия у него нет:
    при чтении (_user_from_token) max_age не передаётся."""
    return signing.dumps(user.pk, salt=TOKEN_SALT)


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _json_body(request):
    # None значит «тело не JSON-объект» — вызывающий код отвечает 400.
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def client_ip(request) -> str:
    """IP клиента. В проде перед Django стоит Caddy: он кладёт адрес клиента последним
    в X-Forwarded-For (подделанные клиентом значения остаются левее), а REMOTE_ADDR — адрес
    самого Caddy."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def _rate_key(scope, key) -> str:
    # Ключ счётчика в кэше: по нему же login проверяет неудачные входы, не увеличивая счётчик.
    return f"rl:{scope}:{key}"


def rate_limit(scope, key, limit, window) -> bool:
    """Засчитывает попытку; False — если в текущем окне `window` секунд их уже больше `limit`.

    Счётчики лежат в кэше Django (по умолчанию в памяти процесса, у каждого воркера gunicorn
    свой), поэтому лимит приблизительный — от перебора паролей этого достаточно.
    """
    cache_key = _rate_key(scope, key)
    # add создаёт счётчик со сроком жизни window, только если его ещё нет; incr срок не
    # продлевает. Так окно отсчитывается от первой попытки, а не сдвигается с каждой новой.
    cache.add(cache_key, 0, window)
    try:
        count = cache.incr(cache_key)
    except ValueError:  # ключ истёк между add и incr
        cache.set(cache_key, 1, window)
        count = 1
    return count <= limit


def _too_many():
    response = _error("Слишком много попыток. Подожди минуту и попробуй снова", status=429)
    response["Retry-After"] = "60"
    return response


# Лимиты подобраны под класс за одним школьным IP: 30 детей входят одновременно.
LOGIN_PER_IP = (60, 60)  # попыток входа с одного IP в минуту
LOGIN_FAILS_PER_USER = (10, 300)  # неверных паролей к одному имени за 5 минут
SIGNUP_PER_IP = (40, 600)  # регистраций с одного IP за 10 минут


def json_post(view):
    """Обёртка для signup/login: только POST, без CSRF, тело уже разобрано в dict
    и передаётся во view вторым аргументом."""

    @csrf_exempt
    @require_POST
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        data = _json_body(request)
        if data is None:
            return _error("Некорректный JSON")
        return view(request, data, *args, **kwargs)

    return wrapper


def _user_from_token(request):
    # Возвращает пользователя или None (нет заголовка, подпись не сошлась, аккаунт выключен).
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER):
        return None
    try:
        user_id = signing.loads(header.removeprefix(BEARER), salt=TOKEN_SALT)
    except signing.BadSignature:
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()


def with_token(view):
    """GET/PUT с авторизацией по токену. Для PUT тело ограничено MAX_SAVE_BYTES."""

    @csrf_exempt
    @require_http_methods(["GET", "PUT"])
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _user_from_token(request)
        if user is None:
            return _error("Нужно войти заново", status=401)
        if request.method != "PUT":
            return view(request, user, None, *args, **kwargs)
        if len(request.body) > MAX_SAVE_BYTES:
            return _error("Сохранение слишком большое", status=413)
        data = _json_body(request)
        if data is None:
            return _error("Некорректный JSON")
        return view(request, user, data, *args, **kwargs)

    return wrapper


def _int(value, default=0):
    # bool в Python — тоже int, поэтому True/False отсекаем отдельно.
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_settings(raw) -> dict:
    """Настройки из сохранения: только известные булевы ключи, остальное — по умолчанию."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        key: raw[key] if isinstance(raw.get(key), bool) else default
        for key, default in SETTINGS_DEFAULTS.items()
    }


def empty_save(name="", avatar="", updated=0) -> dict:
    """Сохранение нового аккаунта: прогресса ещё нет, настройки по умолчанию."""
    return {
        "v": SAVE_VERSION,
        "updated": updated,
        "profile": {"name": name, "avatar": avatar},
        "words": {},
        "days": {},
        "games": {},
        "settings": dict(SETTINGS_DEFAULTS),
    }


def clean_profile(raw: dict) -> dict:
    """Имя и зверёк игрока: строки, обрезанные до NAME_MAX и AVATAR_MAX символов."""
    return {
        "name": str(raw.get("name", "")).strip()[:NAME_MAX],
        "avatar": str(raw.get("avatar", ""))[:AVATAR_MAX],
    }


def _is_timestamp(value) -> bool:
    # updated — целое неотрицательное число (мс). bool отсекаем: в Python это тоже int.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_section(value) -> bool:
    # words/days/games — словарь словарей; внутрь записей не заглядываем.
    return isinstance(value, dict) and all(isinstance(v, dict) for v in value.values())


def clean_save(raw):
    """Проверяет структуру сохранения с телефона. Возвращает очищенную копию или None."""
    if not isinstance(raw, dict) or raw.get("v") != SAVE_VERSION:
        return None
    updated = raw.get("updated")
    profile = raw.get("profile", {})
    if not _is_timestamp(updated) or not isinstance(profile, dict):
        return None
    sections = {section: raw.get(section, {}) for section in SAVE_SECTIONS}
    if not all(_is_section(value) for value in sections.values()):
        return None
    return {
        "v": SAVE_VERSION,
        "updated": updated,
        "profile": clean_profile(profile),
        **sections,
        "settings": clean_settings(raw.get("settings")),
    }


def _profile(user) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _stored_save(profile) -> dict:
    """Хранимое сохранение; у аккаунтов, созданных в админке, его ещё нет. В сохранениях,
    записанных до появления настроек, блок `settings` достраивается на лету."""
    if profile.save_data:
        return {**profile.save_data, "settings": clean_settings(profile.save_data.get("settings"))}
    return empty_save(profile.display_name, profile.avatar, profile.updated)


def _store(profile, save):
    """Записывает сохранение и обновляет копии updated / display_name / avatar для админки."""
    profile.save_data = save
    profile.updated = save["updated"]
    profile.display_name = save["profile"]["name"]
    profile.avatar = save["profile"]["avatar"]
    if profile.pk is None:
        profile.save()
    else:
        profile.save(update_fields=["save_data", "updated", "display_name", "avatar"])


def _account(user, profile) -> dict:
    # Ответ на вход и регистрацию: {token, username, save}.
    return {
        "token": make_token(user),
        "username": user.get_username(),
        "save": _stored_save(profile),
    }


def _signup_error(username, password):
    """Текст ошибки для ребёнка или None, если имя и пароль подходят."""
    if not username or len(username) > USERNAME_MAX:
        return "Придумай имя для входа"
    if any(ch.isspace() for ch in username):
        return "В имени для входа не должно быть пробелов"
    if len(password) < PASSWORD_MIN:
        return f"Пароль должен быть не короче {PASSWORD_MIN} символов"
    if get_user_model().objects.filter(username__iexact=username).exists():
        return "Такое имя уже занято"
    return None


@json_post
def signup(request, data):
    """POST /api/signup {username, password, name, avatar, updated} → 201 {token, username, save}.

    Ошибки проверки — 400 с текстом для ребёнка, слишком много регистраций с IP — 429.
    updated (мс по часам телефона) кладётся в новое сохранение; нет или мусор — 0."""
    if not rate_limit("signup", client_ip(request), *SIGNUP_PER_IP):
        return _too_many()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    error = _signup_error(username, password)
    if error:
        return _error(error)
    profile = clean_profile(data)
    save = empty_save(profile["name"], profile["avatar"], max(_int(data.get("updated")), 0))
    users = get_user_model().objects
    with transaction.atomic():
        user = users.create_user(username=username, password=password)
        profile = Profile(user=user)
        _store(profile, save)
    return JsonResponse(_account(user, profile), status=201)


@json_post
def login(request, data):
    """POST /api/login {username, password} → {token, username, save}; неверно — 401."""
    username = str(data.get("username", "")).strip()
    # Два лимита: общий на IP (считается каждая попытка) и на неверные пароли к одному имени.
    # Второй здесь только проверяется, а растёт ниже — после неудачного входа, поэтому
    # успешные входы его не тратят.
    fails_key = _rate_key("login-fail", username.lower())
    if not rate_limit("login", client_ip(request), *LOGIN_PER_IP):
        return _too_many()
    if cache.get(fails_key, 0) >= LOGIN_FAILS_PER_USER[0]:
        return _too_many()
    user = authenticate(request, username=username, password=str(data.get("password", "")))
    if user is None:
        rate_limit("login-fail", username.lower(), *LOGIN_FAILS_PER_USER)
        return _error("Неверное имя или пароль", status=401)
    return JsonResponse(_account(user, _profile(user)))


@with_token
def save(request, user, data):
    """GET /api/save → {save}; PUT /api/save {save} → {save} или 409 {save: серверное}."""
    if request.method == "GET":
        return JsonResponse({"save": _stored_save(_profile(user))})

    incoming = clean_save(data.get("save"))
    if incoming is None:
        return _error("Некорректное сохранение")
    # select_for_update блокирует строку профиля до конца транзакции: два одновременных PUT
    # с разных телефонов сравнивают updated по очереди, а не оба с одним и тем же старым.
    # Равный updated принимается — это повтор той же отправки.
    with transaction.atomic():
        profile, _ = Profile.objects.select_for_update().get_or_create(user=user)
        stored = _stored_save(profile)
        if incoming["updated"] < stored["updated"]:
            # На сервере новее (например, с другого телефона) — телефон примет серверное.
            return JsonResponse({"save": stored}, status=409)
        _store(profile, incoming)
    return JsonResponse({"save": incoming})
