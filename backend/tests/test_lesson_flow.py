from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.models import Profile
from courses.models import Exercise, Lesson
from learning.models import LessonResult

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def lesson(db):
    call_command("seed")
    return Lesson.objects.order_by("unit__order", "order").first()


def _right_answer(exercise):
    return "ok" if exercise.kind == Exercise.Kind.MATCH else exercise.accepted_answers[0]


@pytest.fixture
def client(client, db):
    """Клиент вошедшего игрока: игровые экраны доступны только после входа."""
    user = get_user_model().objects.create_user(username="player", password="secret123")
    Profile.objects.create(user=user, is_guest=False)
    client.force_login(user)
    return client


def test_anonymous_is_sent_to_login(db):
    response = Client().get(reverse("learning:home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))
    assert not Profile.objects.exists()


def test_logged_in_player_skips_login_page(client):
    assert client.get(reverse("learning:home")).status_code == 200
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 302
    assert response.url == reverse("learning:home")


def test_signup_and_login(db):
    anon = Client()
    anon.post(
        reverse("accounts:signup"),
        {"name": "Айно", "family": "корепанова", "username": "aino", "password": "secret123"},
    )
    profile = Profile.objects.get()
    assert not profile.is_guest
    assert profile.display_name == "Айно К."
    assert "Айно К." in anon.get(reverse("learning:home")).content.decode()
    assert anon.get(reverse("learning:home")).status_code == 200
    anon.post(reverse("accounts:logout"))
    assert anon.get(reverse("learning:home")).status_code == 302
    anon.post(reverse("accounts:login"), {"username": "aino", "password": "secret123"})
    assert anon.get(reverse("learning:home")).status_code == 200


def test_complete_lesson_without_mistakes(client, lesson):
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    for exercise in lesson.exercises.all():
        r = client.post(
            reverse("learning:lesson_answer", args=[lesson.id]),
            {"answer": _right_answer(exercise)},
            **HTMX,
        )
        assert "Верно" in r.content.decode()
        r = client.get(reverse("learning:lesson_next", args=[lesson.id]), **HTMX)

    assert r["HX-Redirect"] == reverse("learning:lesson_result", args=[lesson.id])
    result = LessonResult.objects.get()
    assert result.mistakes == 0
    profile = result.user.profile
    assert profile.xp == result.xp > 0
    assert profile.streak == 1


def test_wrong_answer_costs_heart_and_repeats_exercise(client, lesson):
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    total = lesson.exercises.count()
    client.post(
        reverse("learning:lesson_answer", args=[lesson.id]), {"answer": "абракадабра"}, **HTMX
    )
    run = client.session["lesson_run"]
    assert run["hearts"] == 4
    assert len(run["queue"]) == total + 1


def test_lesson_failed_when_hearts_run_out(client, lesson, settings):
    settings.GAME = settings.GAME | {"MAX_HEARTS": 1}
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    r = client.post(reverse("learning:lesson_answer", args=[lesson.id]), {"answer": "нет"}, **HTMX)
    assert "Сердечки закончились" in r.content.decode()
    assert not LessonResult.objects.exists()


def test_signup_keeps_guest_progress(client, lesson):
    # Гости остались от прежней версии игры; регистрация должна сохранять их аккаунт.
    Profile.objects.update(is_guest=True)
    guest = Profile.objects.get().user
    client.post(
        reverse("accounts:signup"),
        {"name": "Айно", "family": "Корепанова", "username": "aino", "password": "secret123"},
    )
    guest.refresh_from_db()
    assert guest.username == "aino"
    assert not guest.profile.is_guest


def test_profile_shows_progress(client, lesson):
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    for exercise in lesson.exercises.all():
        client.post(
            reverse("learning:lesson_answer", args=[lesson.id]),
            {"answer": _right_answer(exercise)},
            **HTMX,
        )
        client.get(reverse("learning:lesson_next", args=[lesson.id]), **HTMX)

    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert response.context["lessons_done"] == 1
    assert response.context["lessons_total"] == Lesson.objects.count()
    html = response.content.decode()
    assert "player" in html
    assert lesson.title in html


def test_profile_requires_login(db):
    response = Client().get(reverse("accounts:profile"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_admin_cannot_edit_lesson_results(admin_client, lesson):
    admin = get_user_model().objects.get(username="admin")
    result = LessonResult.objects.create(user=admin, lesson=lesson, xp=10)
    change_url = reverse("admin:learning_lessonresult_change", args=[result.id])

    assert admin_client.get(reverse("admin:learning_lessonresult_changelist")).status_code == 200
    assert admin_client.get(change_url).status_code == 200  # только просмотр
    assert admin_client.post(change_url, {"xp": 999}).status_code == 403
    assert admin_client.get(reverse("admin:learning_lessonresult_add")).status_code == 403
    result.refresh_from_db()
    assert result.xp == 10


def test_display_name_falls_back_to_username(db):
    user = get_user_model().objects.create_user(username="aino")
    profile = Profile.objects.create(user=user)
    assert profile.display_name == "aino"
    user.first_name = "Айно"
    assert profile.display_name == "Айно"


def _png(size=(600, 300)):
    buffer = BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return SimpleUploadedFile("me.png", buffer.getvalue(), content_type="image/png")


def test_profile_edit_updates_data_and_avatar(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    url = reverse("accounts:profile_edit")
    data = {"name": "Айно", "family": "Корепанова", "username": "aino"}

    response = client.post(url, data | {"avatar": _png()})
    assert response.status_code == 302
    profile = Profile.objects.select_related("user").get()
    assert profile.user.username == "aino"
    assert profile.display_name == "Айно К."
    with Image.open(profile.avatar.path) as saved:
        assert saved.size == (256, 256)
    assert profile.avatar.url in client.get(reverse("accounts:profile")).content.decode()

    old_path = profile.avatar.path
    client.post(url, data | {"remove_avatar": "on"})
    profile.refresh_from_db()
    assert not profile.avatar
    assert not (tmp_path / old_path).exists()


def test_profile_edit_rejects_taken_username_and_bad_image(client):
    get_user_model().objects.create_user(username="taken")
    url = reverse("accounts:profile_edit")
    data = {"name": "Айно", "family": "Корепанова", "username": "Taken"}
    assert "уже занято" in client.post(url, data).content.decode()

    fake = SimpleUploadedFile("me.png", b"not an image", content_type="image/png")
    response = client.post(url, data | {"username": "aino", "avatar": fake})
    assert response.status_code == 200
    assert get_user_model().objects.filter(username="player").exists()


def test_password_change_from_profile(client):
    assert (
        reverse("accounts:password_change")
        in client.get(reverse("accounts:profile")).content.decode()
    )
    url = reverse("accounts:password_change")
    new = {"new_password1": "newpass", "new_password2": "newpass"}

    response = client.post(url, {"old_password": "wrong"} | new)
    assert response.status_code == 200
    assert get_user_model().objects.get().check_password("secret123")

    response = client.post(url, {"old_password": "secret123"} | new)
    assert response.url == reverse("accounts:profile")
    assert get_user_model().objects.get().check_password("newpass")
    # После смены пароля игрок остаётся в игре.
    assert client.get(reverse("learning:home")).status_code == 200
