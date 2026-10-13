import json
import os
import subprocess
import sys
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils.html import escape
from PIL import Image

from accounts.models import Profile
from courses.models import Exercise, Lesson
from learning.models import LessonResult, PlayerXp

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def lesson(db):
    call_command("seed")
    return Lesson.objects.order_by("unit__order", "order").first()


def _right_answer(exercise):
    if exercise.kind == Exercise.Kind.MATCH:
        return json.dumps(exercise.options)
    return exercise.accepted_answers[0]


def _course_lessons():
    return Lesson.objects.order_by("unit__order", "unit_id", "order", "id")


def _play_lesson(client, lesson):
    """Проходит урок без ошибок."""
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    for exercise in lesson.exercises.all():
        client.post(
            reverse("learning:lesson_answer", args=[lesson.id]),
            {"answer": _right_answer(exercise)},
            **HTMX,
        )
        response = client.get(reverse("learning:lesson_next", args=[lesson.id]), **HTMX)
    return response


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
    response = anon.post(
        reverse("accounts:signup"),
        {"name": "Айно", "family": "корепанова", "username": "aino", "password": "secret123"},
    )
    assert response.url == reverse("learning:welcome")  # после регистрации — правила игры
    profile = Profile.objects.get()
    assert not profile.is_guest
    assert "Сердечки" in anon.get(reverse("learning:welcome")).content.decode()
    assert profile.display_name == "Айно К."
    assert "Айно К." in anon.get(reverse("learning:home")).content.decode()
    assert anon.get(reverse("learning:home")).status_code == 200
    anon.post(reverse("accounts:logout"))
    assert anon.get(reverse("learning:home")).status_code == 302
    anon.post(reverse("accounts:login"), {"username": "aino", "password": "secret123"})
    assert anon.get(reverse("learning:home")).status_code == 200


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


def test_seed_adds_new_lessons_and_keeps_progress(client, lesson, tmp_path):
    player = get_user_model().objects.get(username="player")
    LessonResult.objects.create(user=player, lesson=lesson, xp=10)
    lessons_before = Lesson.objects.count()

    # Повторный запуск ничего не меняет.
    call_command("seed")
    assert Lesson.objects.count() == lessons_before

    extra = tmp_path / "content.yaml"
    extra.write_text(
        """
course: {slug: udmurt-basics, title: Удмуртский для начинающих}
units:
  - title: Новый раздел
    lessons:
      - title: Новый урок
        exercises:
          - {kind: type, prompt: один, answer: одӥг}
""",
        encoding="utf-8",
    )
    call_command("seed", file=str(extra))
    assert Lesson.objects.count() == lessons_before + 1
    assert Lesson.objects.get(title="Новый урок").exercises.count() == 1
    assert LessonResult.objects.filter(lesson=lesson).exists()


def test_every_seed_lesson_can_be_completed(client, lesson):
    """Правильные ответы из content.yaml принимаются во всех уроках (в т.ч. сборка фраз)."""
    for current in _course_lessons():
        client.get(reverse("learning:lesson_start", args=[current.id]))
        for exercise in current.exercises.all():
            r = client.post(
                reverse("learning:lesson_answer", args=[current.id]),
                {"answer": _right_answer(exercise)},
                **HTMX,
            )
            assert "Верно" in r.content.decode(), f"{current}: {exercise}"
            r = client.get(reverse("learning:lesson_next", args=[current.id]), **HTMX)
        assert r["HX-Redirect"] == reverse("learning:lesson_result", args=[current.id])
    assert LessonResult.objects.count() == Lesson.objects.count() >= 25


def _player(username, xp, *, name="", is_guest=False):
    user = get_user_model().objects.create_user(username=username, first_name=name)
    return Profile.objects.create(user=user, xp=xp, is_guest=is_guest)


def test_leaderboard_orders_by_xp_and_marks_player(client):
    Profile.objects.filter(user__username="player").update(xp=50)
    _player("top", 300, name="Айно")
    _player("tie", 50)
    _player("zero", 0)
    _player("guest", 999, is_guest=True)

    response = client.get(reverse("learning:leaderboard"))
    rows = response.context["rows"]
    assert [(r["place"], r["profile"].user.username) for r in rows][0] == (1, "top")
    assert {r["profile"].user.username for r in rows} == {"top", "player", "tie"}
    assert [r["place"] for r in rows] == [1, 2, 2]  # одинаковый опыт — общее место
    assert response.context["my_place"] == 2
    assert response.context["in_top"]
    assert "Айно" in response.content.decode()


def test_leaderboard_anonymous_player(client):
    hidden = _player("secret", 300, name="Тайна")
    hidden.avatar = "avatars/secret.jpg"
    hidden.leaderboard_anonymous = True
    hidden.save()

    page = client.get(reverse("learning:leaderboard")).content.decode()
    assert "Аноним" in page
    assert "Тайна" not in page and "avatars/secret.jpg" not in page

    # Галочка в профиле: сам игрок видит себя под своим именем, с пометкой.
    data = {"name": "Айно", "family": "Корепанова", "username": "player"}
    client.post(reverse("accounts:profile_edit"), data | {"leaderboard_anonymous": "on"})
    me = Profile.objects.get(user__username="player")
    assert me.leaderboard_anonymous
    me.xp = 10
    me.save()
    page = client.get(reverse("learning:leaderboard")).content.decode()
    assert "Айно К." in page and "🕶 аноним" in page
    assert "checked" in client.get(reverse("accounts:profile_edit")).content.decode()

    client.post(reverse("accounts:profile_edit"), data)
    me.refresh_from_db()
    assert not me.leaderboard_anonymous


def test_leaderboard_without_xp_and_for_anonymous(client, db):
    response = client.get(reverse("learning:leaderboard"))
    assert response.context["rows"] == []
    assert response.context["my_place"] is None
    assert Client().get(reverse("learning:leaderboard")).status_code == 302


def test_locked_lesson_is_not_opened_by_direct_link(client, lesson):
    first, second, third = _course_lessons()[:3]
    home = reverse("learning:home")
    for name in ("lesson_start", "lesson_play", "lesson_next"):
        response = client.get(reverse(f"learning:{name}", args=[third.id]))
        assert response.status_code == 302
        assert response.url == home
    response = client.post(
        reverse("learning:lesson_answer", args=[third.id]), {"answer": "x"}, **HTMX
    )
    assert response["HX-Redirect"] == home
    assert "lesson_run" not in client.session

    # Пройден первый урок — открыт второй, третий всё ещё закрыт.
    _play_lesson(client, first)
    assert client.get(reverse("learning:lesson_start", args=[second.id])).url.endswith(
        f"/lesson/{second.id}/"
    )
    assert client.get(reverse("learning:lesson_start", args=[third.id])).url == home
    states = {
        i["obj"].id: i["open"] for u in client.get(home).context["units"] for i in u["lessons"]
    }
    assert states[first.id] and states[second.id] and not states[third.id]


def test_course_map_lesson_labels_and_locked_hint(client, lesson):
    """Карта курса: у уроков есть aria-label с названием и состоянием, подпись — часть ссылки,
    у закрытого урока — подсказка «Сначала пройди предыдущий урок»."""
    first, second, third = _course_lessons()[:3]
    _play_lesson(client, first)
    html = client.get(reverse("learning:home")).content.decode()
    start = reverse("learning:lesson_start", args=[first.id])
    assert f'href="{start}" class="flex flex-col items-center"' in html
    assert f'aria-label="{escape(first.title)} — пройден"' in html
    assert f'aria-label="{escape(second.title)} — не пройден"' in html
    assert f'aria-label="{escape(third.title)} — закрыт"' in html
    assert "Сначала пройди предыдущий урок" in html


def _start_match(client):
    exercise = Exercise.objects.filter(kind=Exercise.Kind.MATCH).select_related("lesson").first()
    lesson = exercise.lesson
    # Открываем урок: все предыдущие отмечены пройденными.
    player = get_user_model().objects.get(username="player")
    for previous in _course_lessons():
        if previous == lesson:
            break
        LessonResult.objects.create(user=player, lesson=previous)
    client.get(reverse("learning:lesson_start", args=[lesson.id]))
    session = client.session
    session["lesson_run"]["queue"] = [exercise.id]
    session.save()
    return exercise


@pytest.mark.parametrize("answer", ["ok", "", "[]", "[[1, 2]]", "{}"])
def test_match_without_right_pairs_is_wrong(client, lesson, answer):
    exercise = _start_match(client)
    if answer == "":
        answer = json.dumps([[left, "не то"] for left, _ in exercise.options])
    r = client.post(
        reverse("learning:lesson_answer", args=[exercise.lesson_id]), {"answer": answer}, **HTMX
    )
    assert "Неверно" in r.content.decode()
    assert client.session["lesson_run"]["hearts"] == 4


def test_match_mistakes_are_counted_without_losing_hearts(client, lesson):
    exercise = _start_match(client)
    pairs = list(reversed(exercise.options))  # порядок пар не важен
    r = client.post(
        reverse("learning:lesson_answer", args=[exercise.lesson_id]),
        {"answer": json.dumps(pairs), "mistakes": "2"},
        **HTMX,
    )
    assert "Верно" in r.content.decode()
    run = client.session["lesson_run"]
    assert run["hearts"] == 5
    assert run["mistakes"] == 2
    client.get(reverse("learning:lesson_next", args=[exercise.lesson_id]), **HTMX)
    assert LessonResult.objects.get(lesson=exercise.lesson, xp__gt=0).mistakes == 2


def test_replayed_lesson_adds_no_xp_without_new_record(client, lesson):
    _play_lesson(client, lesson)
    first = LessonResult.objects.get()
    profile = Profile.objects.get(user__username="player")
    total_xp = profile.xp
    _play_lesson(client, lesson)
    replay = LessonResult.objects.order_by("-id").first()
    assert replay.xp == first.xp
    profile.refresh_from_db()
    assert profile.xp == total_xp
    result = client.get(reverse("learning:lesson_result", args=[lesson.id]))
    assert "Рекорд не побит" in result.content.decode()


def test_empty_answer_costs_no_heart(client, lesson):
    exercise = Exercise.objects.filter(kind=Exercise.Kind.ASSEMBLE).first()
    player = get_user_model().objects.get(username="player")
    for previous in _course_lessons():
        if previous == exercise.lesson:
            break
        LessonResult.objects.create(user=player, lesson=previous)
    client.get(reverse("learning:lesson_start", args=[exercise.lesson_id]))
    session = client.session
    session["lesson_run"]["queue"] = [exercise.id]
    session.save()
    r = client.post(
        reverse("learning:lesson_answer", args=[exercise.lesson_id]), {"answer": " "}, **HTMX
    )
    html = r.content.decode()
    assert "Неверно" not in html
    assert "Проверить" in html
    run = client.session["lesson_run"]
    assert run["hearts"] == 5 and not run["answered"]


def test_lesson_exit_asks_for_confirmation(client, lesson):
    html = client.get(reverse("learning:lesson_start", args=[lesson.id]), follow=True)
    assert "Выйти из урока?" in html.content.decode()


def test_404_page_is_russian(client):
    response = client.get("/nет-такой-страницы/")
    assert response.status_code == 404
    assert "Такой страницы нет" in response.content.decode()


@pytest.mark.parametrize("taken", ["демо", "Демо", "demo"])
def test_username_taken_ignores_cyrillic_case(db, taken):
    get_user_model().objects.create_user(username=taken)
    response = Client().post(
        reverse("accounts:signup"),
        {"name": "Айно", "family": "К", "username": taken.upper(), "password": "secret123"},
    )
    assert "уже занято" in response.content.decode()
    assert get_user_model().objects.count() == 1


def test_profile_edit_rejects_taken_cyrillic_username(client):
    get_user_model().objects.create_user(username="демо")
    data = {"name": "Айно", "family": "Корепанова", "username": "ДЕМО"}
    assert "уже занято" in client.post(reverse("accounts:profile_edit"), data).content.decode()
    # Своё имя, набранное в другом регистре, — не «занято».
    data["username"] = "PLAYER"
    assert client.post(reverse("accounts:profile_edit"), data).status_code == 302


@pytest.mark.parametrize("https_only", ["0", "1"])
def test_secure_cookies_and_hsts_on_https(https_only):
    code = (
        "from config import settings as s; "
        "print(getattr(s, 'SESSION_COOKIE_SECURE', False), getattr(s, 'CSRF_COOKIE_SECURE', False),"
        " getattr(s, 'SECURE_HSTS_SECONDS', 0))"
    )
    env = os.environ | {"DJANGO_HTTPS_ONLY": https_only}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout.split()
    if https_only == "1":
        assert out == ["True", "True", "31536000"]
    else:
        assert out == ["False", "False", "0"]
