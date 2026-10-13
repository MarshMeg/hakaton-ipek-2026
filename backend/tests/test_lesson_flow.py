import pytest
from django.core.management import call_command
from django.urls import reverse

from accounts.models import Profile
from courses.models import Exercise, Lesson
from learning.models import LessonResult, PlayerXp

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def lesson(db):
    call_command("seed")
    return Lesson.objects.order_by("unit__order", "order").first()


def _right_answer(exercise):
    return "ok" if exercise.kind == Exercise.Kind.MATCH else exercise.accepted_answers[0]


def test_home_creates_guest(client, db):
    response = client.get(reverse("learning:home"))
    assert response.status_code == 200
    assert Profile.objects.filter(is_guest=True).count() == 1


def _play(client, lesson, wrong_first=False):
    """Проходит урок до конца; wrong_first — ошибиться в первом упражнении."""
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    queue = list(lesson.exercises.all())
    if wrong_first:
        queue.append(queue[0])
    for i, exercise in enumerate(queue):
        answer = "абракадабра" if wrong_first and i == 0 else _right_answer(exercise)
        r = client.post(
            reverse("learning:lesson_answer", args=[lesson.id]), {"answer": answer}, **HTMX
        )
        r = client.get(reverse("learning:lesson_next", args=[lesson.id]), **HTMX)
    assert r["HX-Redirect"] == reverse("learning:lesson_result", args=[lesson.id])


def test_complete_lesson_without_mistakes(client, lesson):
    _play(client, lesson)
    total = lesson.exercises.count()
    result = LessonResult.objects.get()
    assert result.mistakes == 0
    assert result.accuracy == 1.0
    assert result.max_combo == total
    assert result.xp == 10 * total
    profile = result.user.profile
    # Суммарный опыт считает представление БД: результат урока + бонус 10 за первый урок.
    assert profile.xp == PlayerXp.objects.get(user=result.user).xp == result.xp + 10
    assert profile.streak == 1
    page = client.get(reverse("learning:lesson_result", args=[lesson.id])).content.decode()
    assert "100%" in page
    assert f"+{profile.xp}" in page


def test_worse_replay_keeps_xp_and_streak(client, lesson):
    _play(client, lesson)
    profile = Profile.objects.get()
    best_xp = profile.xp
    _play(client, lesson, wrong_first=True)
    worse, best = LessonResult.objects.all()  # сортировка: новые первыми
    assert worse.mistakes == 1
    assert worse.xp < best.xp
    assert worse.accuracy < 1.0
    profile.refresh_from_db()
    assert profile.xp == best_xp
    assert profile.streak == 1
    page = client.get(reverse("learning:lesson_result", args=[lesson.id])).content.decode()
    assert "Рекорд не побит" in page


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
    client.get(reverse("learning:home"))
    guest = Profile.objects.get().user
    client.post(reverse("accounts:signup"), {"username": "aino", "password": "secret123"})
    guest.refresh_from_db()
    assert guest.username == "aino"
    assert not guest.profile.is_guest
