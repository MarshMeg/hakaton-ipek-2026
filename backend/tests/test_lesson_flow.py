import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

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
    """Клиент, вошедший как гость: игровые экраны доступны только после входа."""
    client.post(reverse("accounts:guest"))
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


def test_guest_button_creates_guest(client):
    assert Profile.objects.filter(is_guest=True).count() == 1


def test_signup_and_login_without_guest(db):
    anon = Client()
    anon.post(reverse("accounts:signup"), {"username": "aino", "password": "secret123"})
    assert not Profile.objects.get().is_guest
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
    guest = Profile.objects.get().user
    client.post(reverse("accounts:signup"), {"username": "aino", "password": "secret123"})
    guest.refresh_from_db()
    assert guest.username == "aino"
    assert not guest.profile.is_guest
