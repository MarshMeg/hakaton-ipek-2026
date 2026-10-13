import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from courses.models import Lesson
from learning.models import LessonResult, PlayerXp
from learning.services import scoring
from learning.services.answer_check import Verdict


def test_hit_value():
    assert scoring.hit_value(Verdict.CORRECT, first_try=True) == 100
    assert scoring.hit_value(Verdict.ALMOST, first_try=True) == 50
    assert scoring.hit_value(Verdict.CORRECT, first_try=False) == 10
    assert scoring.hit_value(Verdict.ALMOST, first_try=False) == 10
    assert scoring.hit_value(Verdict.WRONG, first_try=True) == 0
    assert scoring.hit_value(Verdict.WRONG, first_try=False) == 0


def test_combo_grows_score():
    assert [scoring.combo_score(100, combo) for combo in range(4)] == [100, 110, 120, 130]
    assert scoring.max_score(4) == 460


def test_perfect_lesson():
    assert scoring.accuracy({"1": 100, "2": 100, "3": 100, "4": 100}, 4) == 1.0
    assert scoring.lesson_xp(scoring.max_score(4), 4) == 40


def test_lesson_with_one_mistake():
    # Ошибка во 2-м упражнении из 4 (комбо сброшено), верно на повторе в конце.
    score = sum(
        scoring.combo_score(hit, combo)
        for hit, combo in [(100, 0), (0, 1), (100, 0), (100, 1), (10, 2)]
    )
    assert score == 322
    assert scoring.lesson_xp(score, 4) == 28
    assert scoring.accuracy({"1": 100, "2": 10, "3": 100, "4": 100}, 4) == pytest.approx(0.775)


def test_lesson_xp_is_at_least_one():
    assert scoring.lesson_xp(0, 4) == 1


@pytest.fixture
def lessons(db):
    call_command("seed")
    return list(Lesson.objects.order_by("unit__order", "order")[:4])


@pytest.fixture
def user(db):
    return get_user_model().objects.create(username="player")


def test_player_xp_is_weighted_sum_of_best_results(user, lessons):
    for lesson, xp in zip(lessons, [40, 50, 30, 40], strict=True):
        LessonResult.objects.create(user=user, lesson=lesson, xp=xp)
    # 50 + 40·0.95 + 40·0.95² + 30·0.95³ = 149.8; бонус 100·(1 − 0.9⁴) = 34.4
    total = PlayerXp.objects.get(user=user)
    assert total.xp == 184
    assert total.lessons_done == 4


def test_player_xp_counts_only_best_result_per_lesson(user, lessons):
    LessonResult.objects.create(user=user, lesson=lessons[0], xp=40)
    assert PlayerXp.objects.get(user=user).xp == 50  # 40 + бонус 10 за первый урок
    LessonResult.objects.create(user=user, lesson=lessons[0], xp=25)
    assert PlayerXp.objects.get(user=user).xp == 50
    LessonResult.objects.create(user=user, lesson=lessons[0], xp=45)
    assert PlayerXp.objects.get(user=user).xp == 55


def test_player_without_results_has_no_xp(user):
    assert not PlayerXp.objects.filter(user=user).exists()
