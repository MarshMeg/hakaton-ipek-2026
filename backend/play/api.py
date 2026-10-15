"""JSON API аккаунта: регистрация, вход и «сохранение» прогресса.

Сохранение — один JSON-документ на аккаунт (профиль и агрегированный прогресс) с полем
`updated` (мс, по часам телефона):

    {"v": 2, "updated": 1760500000000,
     "profile": {"name": "Аня", "avatar": "🦊"},
     "words": {"17": {"ok": 3, "bad": 1, "seen": 2, "streak": 2, "last": 1760500000000}},
     "days": {"2026-10-15": {"ok": 12, "bad": 3, "seen": 5}},
     "games": {"choose": {"ok": 20, "bad": 4, "played": 3, "best": 3}}}

`streak` — верные ответы на слово подряд (после ошибки — 0): после трёх подряд слово
перестаёт быть «трудным» (режим «Трудные слова», `ZB.hardWords` в static/js/app.js). В старых
сохранениях поля нет, клиент считает его нулём.

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


def make_token(user) -> str:
    return signing.dumps(user.pk, salt=TOKEN_SALT)


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _json_body(request):
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


def rate_limit(scope, key, limit, window) -> bool:
    """Засчитывает попытку; False — если в текущем окне `window` секунд их уже больше `limit`.

    Счётчики лежат в кэше Django (по умолчанию в памяти процесса, у каждого воркера gunicorn
    свой), поэтому лимит приблизительный — от перебора паролей этого достаточно.
    """
    cache_key = f"rl:{scope}:{key}"
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
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        user_id = signing.loads(header[7:], salt=TOKEN_SALT)
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
        data = None
        if request.method == "PUT":
            if len(request.body) > MAX_SAVE_BYTES:
                return _error("Сохранение слишком большое", status=413)
            data = _json_body(request)
            if data is None:
                return _error("Некорректный JSON")
        return view(request, user, data, *args, **kwargs)

    return wrapper


def _int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_save(name="", avatar="", updated=0) -> dict:
    return {
        "v": SAVE_VERSION,
        "updated": updated,
        "profile": {"name": name, "avatar": avatar},
        "words": {},
        "days": {},
        "games": {},
    }


def clean_save(raw):
    """Проверяет структуру сохранения с телефона. Возвращает очищенную копию или None."""
    if not isinstance(raw, dict) or raw.get("v") != SAVE_VERSION:
        return None
    updated = raw.get("updated")
    if not isinstance(updated, int) or isinstance(updated, bool) or updated < 0:
        return None
    profile = raw.get("profile", {})
    if not isinstance(profile, dict):
        return None
    save = {
        "v": SAVE_VERSION,
        "updated": updated,
        "profile": {
            "name": str(profile.get("name", ""))[:60],
            "avatar": str(profile.get("avatar", ""))[:16],
        },
    }
    for section in SAVE_SECTIONS:
        value = raw.get(section, {})
        if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
            return None
        save[section] = value
    return save


def _profile(user) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _stored_save(profile) -> dict:
    """Хранимое сохранение; у аккаунтов, созданных в админке, его ещё нет."""
    if profile.save_data:
        return profile.save_data
    return empty_save(profile.display_name, profile.avatar, profile.updated)


def _store(profile, save):
    profile.save_data = save
    profile.updated = save["updated"]
    profile.display_name = save["profile"]["name"]
    profile.avatar = save["profile"]["avatar"]
    if profile.pk is None:
        profile.save()
    else:
        profile.save(update_fields=["save_data", "updated", "display_name", "avatar"])


def _account(user, profile) -> dict:
    return {
        "token": make_token(user),
        "username": user.get_username(),
        "save": _stored_save(profile),
    }


@json_post
def signup(request, data):
    if not rate_limit("signup", client_ip(request), *SIGNUP_PER_IP):
        return _too_many()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or len(username) > 150:
        return _error("Придумай имя для входа")
    if len(password) < 6:
        return _error("Пароль должен быть не короче 6 символов")
    users = get_user_model().objects
    if users.filter(username__iexact=username).exists():
        return _error("Такое имя уже занято")
    save = empty_save(
        str(data.get("name", ""))[:60],
        str(data.get("avatar", ""))[:16],
        max(_int(data.get("updated")), 0),
    )
    with transaction.atomic():
        user = users.create_user(username=username, password=password)
        profile = Profile(user=user)
        _store(profile, save)
    return JsonResponse(_account(user, profile), status=201)


@json_post
def login(request, data):
    username = str(data.get("username", "")).strip()
    # Два лимита: общий на IP (считается каждая попытка) и на неверные пароли к одному имени.
    # Второй здесь только проверяется, а растёт ниже — после неудачного входа, поэтому
    # успешные входы его не тратят. Ключ — тот же, что строит rate_limit("login-fail", …).
    fails_key = f"rl:login-fail:{username.lower()}"
    if not rate_limit("login", client_ip(request), *LOGIN_PER_IP) or (
        cache.get(fails_key, 0) >= LOGIN_FAILS_PER_USER[0]
    ):
        return _too_many()
    user = authenticate(request, username=username, password=str(data.get("password", "")))
    if user is None:
        rate_limit("login-fail", username.lower(), *LOGIN_FAILS_PER_USER)
        return _error("Неверное имя или пароль", status=401)
    return JsonResponse(_account(user, _profile(user)))


@with_token
def save(request, user, data):
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
