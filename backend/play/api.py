"""JSON API облачного аккаунта: регистрация, вход и синхронизация прогресса.

Прогресс живёт на телефоне и пишется без сети. Когда сеть есть, телефон отправляет
неотправленные события и получает все события аккаунта (в том числе с других устройств).
События идентифицируются uuid, поэтому синхронизация — это объединение множеств:
ничего не теряется и не дублируется.

Авторизация — токен в заголовке `Authorization: Bearer …` (подписанный id пользователя),
без cookies, поэтому CSRF здесь не нужен.
"""

import json
import uuid
from functools import wraps

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Profile

from .models import Attempt

TOKEN_SALT = "votes.api"
MAX_EVENTS_PER_SYNC = 5000


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


def _account(user) -> dict:
    profile, _ = Profile.objects.get_or_create(user=user)
    return {
        "token": make_token(user),
        "username": user.get_username(),
        "profile": {
            "name": profile.display_name,
            "avatar": profile.avatar,
            "updated": profile.updated,
        },
    }


@json_post
def signup(request, data):
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or len(username) > 150:
        return _error("Придумай имя для входа")
    if len(password) < 6:
        return _error("Пароль должен быть не короче 6 символов")
    users = get_user_model().objects
    if users.filter(username__iexact=username).exists():
        return _error("Такое имя уже занято")
    with transaction.atomic():
        user = users.create_user(username=username, password=password)
        Profile.objects.create(
            user=user,
            display_name=str(data.get("name", ""))[:60],
            avatar=str(data.get("avatar", ""))[:16],
            updated=_int(data.get("updated")),
        )
    return JsonResponse(_account(user), status=201)


@json_post
def login(request, data):
    user = authenticate(
        request,
        username=str(data.get("username", "")).strip(),
        password=str(data.get("password", "")),
    )
    if user is None:
        return _error("Неверное имя или пароль", status=401)
    return JsonResponse(_account(user))


def _user_from_token(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        user_id = signing.loads(header[7:], salt=TOKEN_SALT)
    except signing.BadSignature:
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_event(raw):
    """Событие с телефона: {id, w, g, c, t}. Некорректные события пропускаем молча."""
    if not isinstance(raw, dict):
        return None
    try:
        event_id = uuid.UUID(str(raw["id"]))
    except (KeyError, ValueError):
        return None
    correct = raw.get("c")
    return {
        "uuid": event_id,
        "word_id": max(_int(raw.get("w")), 0),
        "game": str(raw.get("g", ""))[:16],
        "correct": None if correct is None else bool(correct),
        "ts": _int(raw.get("t")),
    }


@json_post
def sync(request, data):
    user = _user_from_token(request)
    if user is None:
        return _error("Нужно войти заново", status=401)

    events = data.get("events") or []
    if not isinstance(events, list) or len(events) > MAX_EVENTS_PER_SYNC:
        return _error("Слишком много событий за раз")
    parsed = [e for e in map(_parse_event, events) if e]
    Attempt.objects.bulk_create([Attempt(user=user, **e) for e in parsed], ignore_conflicts=True)

    # Имя и аватар: побеждает более поздняя правка (время правки присылает телефон).
    profile, _ = Profile.objects.get_or_create(user=user)
    client = data.get("profile")
    if isinstance(client, dict) and _int(client.get("updated")) > profile.updated:
        profile.display_name = str(client.get("name", ""))[:60]
        profile.avatar = str(client.get("avatar", ""))[:16]
        profile.updated = _int(client.get("updated"))
        profile.save(update_fields=["display_name", "avatar", "updated"])

    rows = user.attempts.values_list("uuid", "word_id", "game", "correct", "ts")
    return JsonResponse(
        {
            "profile": {
                "name": profile.display_name,
                "avatar": profile.avatar,
                "updated": profile.updated,
            },
            "events": [
                {"id": str(u), "w": w, "g": g, "c": None if c is None else int(c), "t": t}
                for u, w, g, c, t in rows
            ],
        }
    )
