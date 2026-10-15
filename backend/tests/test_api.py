import json
import uuid

import pytest
from django.contrib.auth import get_user_model

from play.models import Attempt


def post(client, url, data, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(url, json.dumps(data), content_type="application/json", **headers)


def event(word=1, correct=1, ts=1000):
    return {"id": str(uuid.uuid4()), "w": word, "g": "choose", "c": correct, "t": ts}


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


def test_signup_validation(client, token):
    assert (
        post(client, "/api/signup", {"username": "AINO", "password": "secret123"}).json()["error"]
        == "Такое имя уже занято"
    )
    assert post(client, "/api/signup", {"username": "bob", "password": "123"}).status_code == 400


def test_login(client, token):
    r = post(client, "/api/login", {"username": "aino", "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["profile"] == {"name": "Айно", "avatar": "🦊", "updated": 10}
    assert post(client, "/api/login", {"username": "aino", "password": "nope"}).status_code == 401


def test_sync_requires_valid_token(client, db):
    assert post(client, "/api/sync", {"events": []}).status_code == 401
    assert post(client, "/api/sync", {"events": []}, token="forged").status_code == 401


def test_sync_is_idempotent_union(client, token):
    a, b = event(word=1), event(word=2, correct=0)
    r = post(client, "/api/sync", {"events": [a, b]}, token)
    assert r.status_code == 200
    # Повторная отправка (например, после обрыва связи) ничего не дублирует.
    post(client, "/api/sync", {"events": [a, b]}, token)
    assert Attempt.objects.count() == 2

    # Второе устройство присылает своё событие и получает все.
    c = event(word=3, correct=None)
    data = post(client, "/api/sync", {"events": [c]}, token).json()
    assert {e["id"] for e in data["events"]} == {a["id"], b["id"], c["id"]}
    view = next(e for e in data["events"] if e["id"] == c["id"])
    assert view["c"] is None


def test_sync_skips_garbage_events(client, token):
    r = post(client, "/api/sync", {"events": [{"id": "not-a-uuid"}, "junk", event()]}, token)
    assert r.status_code == 200
    assert Attempt.objects.count() == 1


def test_profile_last_write_wins(client, token):
    post(client, "/api/sync", {"profile": {"name": "Старое", "avatar": "🐻", "updated": 5}}, token)
    user = get_user_model().objects.get(username="aino")
    assert user.profile.display_name == "Айно"
    data = post(
        client, "/api/sync", {"profile": {"name": "Новое", "avatar": "🐻", "updated": 20}}, token
    ).json()
    assert data["profile"] == {"name": "Новое", "avatar": "🐻", "updated": 20}


def test_api_rejects_bad_json(client, db):
    r = client.post("/api/login", "{", content_type="application/json")
    assert r.status_code == 400
