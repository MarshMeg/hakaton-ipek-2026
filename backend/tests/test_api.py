import importlib
import json

import pytest
from django.contrib.auth import get_user_model

from accounts.models import Profile
from play.api import (
    LOGIN_FAILS_PER_USER,
    MAX_SAVE_BYTES,
    SETTINGS_DEFAULTS,
    SIGNUP_PER_IP,
    clean_save,
)

migration = importlib.import_module("accounts.migrations.0005_profile_save")


def post(client, url, data):
    return client.post(url, json.dumps(data), content_type="application/json")


def auth(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}


def get_save(client, token=None):
    return client.get("/api/save", **auth(token))


def put_save(client, save, token=None):
    body = json.dumps({"save": save})
    return client.put("/api/save", body, content_type="application/json", **auth(token))


def make_save(updated, ok=1):
    return {
        "v": 2,
        "updated": updated,
        "profile": {"name": "Айно", "avatar": "🦊"},
        "words": {"17": {"ok": ok, "bad": 0, "seen": 0, "last": updated}},
        "days": {"2026-10-15": {"ok": ok, "bad": 0, "seen": 0}},
        "games": {"choose": {"ok": ok, "bad": 0, "played": 1, "best": 3}},
        "settings": dict(SETTINGS_DEFAULTS),
    }


@pytest.fixture
def token(client, db):
    r = post(
        client,
        "/api/signup",
        {
            "username": "aino",
            "password": "secret123",
            "name": "Айно",
            "avatar": "🦊",
            "updated": 10,
        },
    )
    assert r.status_code == 201
    return r.json()["token"]


def test_signup_returns_empty_save(client, db):
    r = post(
        client,
        "/api/signup",
        {
            "username": "aino",
            "password": "secret123",
            "name": "Айно",
            "avatar": "🦊",
            "updated": 10,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["username"] == "aino"
    assert data["token"]
    assert data["save"] == {
        "v": 2,
        "updated": 10,
        "profile": {"name": "Айно", "avatar": "🦊"},
        "words": {},
        "days": {},
        "games": {},
        "settings": {"sound": True, "notifications": False, "geo": False},
    }


def test_signup_validation(client, token):
    r = post(client, "/api/signup", {"username": "AINO", "password": "secret123"})
    assert r.status_code == 400
    assert r.json()["error"] == "Такое имя уже занято"
    assert post(client, "/api/signup", {"username": "bob", "password": "123"}).status_code == 400


def test_signup_strips_name(client, db):
    # Имя из одних пробелов сохраняется пустым — тогда приложение показывает логин.
    r = post(client, "/api/signup", {"username": "bob", "password": "secret123", "name": "   "})
    assert r.json()["save"]["profile"]["name"] == ""
    r = post(client, "/api/signup", {"username": "eva", "password": "secret123", "name": " Ева "})
    assert r.json()["save"]["profile"]["name"] == "Ева"


def test_put_save_strips_name(client, token):
    save = make_save(20)
    save["profile"]["name"] = " \t "
    r = put_save(client, save, token)
    assert r.status_code == 200
    assert get_save(client, token).json()["save"]["profile"]["name"] == ""


def test_login_returns_save(client, token):
    put_save(client, make_save(20), token)
    r = post(client, "/api/login", {"username": "aino", "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["save"] == make_save(20)
    assert post(client, "/api/login", {"username": "aino", "password": "nope"}).status_code == 401


def test_save_requires_valid_token(client, db):
    assert get_save(client).status_code == 401
    assert get_save(client, "forged").status_code == 401
    assert put_save(client, make_save(20)).status_code == 401
    assert put_save(client, make_save(20), "forged").status_code == 401


def test_put_newer_is_stored(client, token):
    r = put_save(client, make_save(20), token)
    assert r.status_code == 200
    assert get_save(client, token).json()["save"] == make_save(20)
    profile = get_user_model().objects.get(username="aino").profile
    assert (profile.updated, profile.display_name, profile.avatar) == (20, "Айно", "🦊")


def test_put_same_updated_is_accepted(client, token):
    put_save(client, make_save(20, ok=1), token)
    r = put_save(client, make_save(20, ok=2), token)
    assert r.status_code == 200
    assert get_save(client, token).json()["save"]["words"]["17"]["ok"] == 2


def test_put_older_conflicts(client, token):
    put_save(client, make_save(30, ok=5), token)
    r = put_save(client, make_save(20, ok=1), token)
    assert r.status_code == 409
    assert r.json()["save"] == make_save(30, ok=5)


def test_put_normalizes_profile(client, token):
    save = make_save(20)
    save["profile"] = {"name": "Я" * 100, "avatar": "🦊" * 20}
    data = put_save(client, save, token).json()["save"]
    assert len(data["profile"]["name"]) == 60
    assert len(data["profile"]["avatar"]) == 16


@pytest.mark.parametrize(
    "patch",
    [
        {"v": 1},
        {"updated": "20"},
        {"updated": True},
        {"words": []},
        {"days": {"2026-10-15": 3}},
        {"profile": "Айно"},
    ],
)
def test_put_invalid_save(client, token, patch):
    save = make_save(20)
    save.update(patch)
    assert put_save(client, save, token).status_code == 400


def test_settings_are_stored(client, token):
    save = make_save(20)
    save["settings"] = {"sound": False, "notifications": True, "geo": True}
    assert put_save(client, save, token).status_code == 200
    assert get_save(client, token).json()["save"]["settings"] == save["settings"]


def test_clean_save_without_settings_gets_defaults():
    """Сохранение, записанное до появления настроек, читается с настройками по умолчанию."""
    save = make_save(20)
    del save["settings"]
    assert clean_save(save)["settings"] == {"sound": True, "notifications": False, "geo": False}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("громко", SETTINGS_DEFAULTS),
        ([False], SETTINGS_DEFAULTS),
        (
            {"sound": 0, "notifications": "true", "geo": None},
            SETTINGS_DEFAULTS,
        ),
        (
            {"sound": False, "theme": "dark", "volume": 5},
            {"sound": False, "notifications": False, "geo": False},
        ),
        ({"geo": True}, {"sound": True, "notifications": False, "geo": True}),
    ],
)
def test_clean_save_settings_garbage(raw, expected):
    """Мусор в настройках не ломает сохранение: неизвестные ключи отбрасываются,
    не булевы значения заменяются значениями по умолчанию."""
    save = make_save(20)
    save["settings"] = raw
    assert clean_save(save)["settings"] == expected


def test_stored_save_without_settings_is_readable(client, token):
    """В базе лежит сохранение без settings (записано старой версией) — GET достраивает блок."""
    old = make_save(20)
    del old["settings"]
    Profile.objects.filter(user__username="aino").update(save_data=old, updated=20)
    data = get_save(client, token).json()["save"]
    assert data["settings"] == SETTINGS_DEFAULTS
    assert data["words"] == old["words"]
    # Более старое присланное по-прежнему отклоняется, ответ — тоже с настройками.
    r = put_save(client, make_save(5), token)
    assert r.status_code == 409
    assert r.json()["save"]["settings"] == SETTINGS_DEFAULTS


def test_put_too_large(client, token):
    save = make_save(20)
    save["words"] = {str(i): {"ok": 1, "bad": 0, "seen": 0, "last": 0} for i in range(10000)}
    assert len(json.dumps(save)) > MAX_SAVE_BYTES
    assert put_save(client, save, token).status_code == 413


def test_api_rejects_bad_json(client, token):
    assert client.post("/api/login", "{", content_type="application/json").status_code == 400
    r = client.put("/api/save", "{", content_type="application/json", **auth(token))
    assert r.status_code == 400


def test_login_locks_after_failed_attempts(client, token):
    for _ in range(LOGIN_FAILS_PER_USER[0]):
        assert (
            post(client, "/api/login", {"username": "aino", "password": "nope"}).status_code == 401
        )
    # Дальше отказ даже с верным паролем — до конца окна, и регистр имени не помогает.
    r = post(client, "/api/login", {"username": "AINO", "password": "secret123"})
    assert r.status_code == 429
    assert r["Retry-After"] == "60"


def test_signup_is_limited_per_ip(client, db):
    def signup(i, ip):
        data = {"username": f"kid{i}", "password": "secret123"}
        body = json.dumps(data)
        return client.post(
            "/api/signup", body, content_type="application/json", HTTP_X_FORWARDED_FOR=ip
        )

    for i in range(SIGNUP_PER_IP[0]):
        assert signup(i, "1.2.3.4, 10.0.0.1").status_code == 201
    assert signup(999, "1.2.3.4, 10.0.0.1").status_code == 429
    # Учитывается последний адрес (его добавил Caddy), а не подделанный клиентом первый.
    assert signup(1000, "1.2.3.4, 10.0.0.2").status_code == 201


def test_build_save_from_attempts():
    day = 1760500000000  # 2025-10-15 07:46 по Ижевску
    rows = [
        (17, "choose", True, day),
        (17, "choose", False, day + 1000),
        (17, "card", None, day + 2000),
        (5, "memory", True, day + 86400000),
    ]
    save = migration.build_save(rows, "Айно", "🦊", profile_updated=5)
    assert save == {
        "v": 2,
        "updated": day + 86400000,
        "profile": {"name": "Айно", "avatar": "🦊"},
        "words": {
            "17": {"ok": 1, "bad": 1, "seen": 1, "last": day + 2000},
            "5": {"ok": 1, "bad": 0, "seen": 0, "last": day + 86400000},
        },
        "days": {
            "2025-10-15": {"ok": 1, "bad": 1, "seen": 1},
            "2025-10-16": {"ok": 1, "bad": 0, "seen": 0},
        },
        "games": {
            "choose": {"ok": 1, "bad": 1, "played": 0, "best": 0},
            "memory": {"ok": 1, "bad": 0, "played": 0, "best": 0},
        },
    }
