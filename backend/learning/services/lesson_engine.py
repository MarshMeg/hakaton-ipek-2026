"""Прохождение урока. Состояние текущего прохождения хранится в сессии пользователя.

Правила (как в Duolingo):
- у игрока есть «сердечки»; за ошибку теряется одно, при нуле урок проигран;
- упражнение с ошибкой один раз повторяется в конце урока;
- опыт начисляется за верные ответы с первой попытки + бонус за прохождение урока;
- за повтор уже пройденного урока — половина опыта (чтобы не накручивать таблицу лидеров);
- в «Найди пары» неверная пара сердечко не отнимает, но считается ошибкой в итогах урока.
"""

import json
import random
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from courses.models import Exercise, Lesson
from learning.models import LessonResult

from .answer_check import Verdict, check_answer

SESSION_KEY = "lesson_run"
RESULT_KEY = "lesson_result"


@dataclass
class Feedback:
    verdict: Verdict
    correct_answer: str


def start(session, lesson: Lesson) -> None:
    queue = list(lesson.exercises.values_list("id", flat=True))
    session[SESSION_KEY] = {
        "lesson_id": lesson.id,
        "queue": queue,
        "pos": 0,
        "hearts": settings.GAME["MAX_HEARTS"],
        "xp": 0,
        "mistakes": 0,
        "answered": False,
        "retried": [],
    }


def get_run(session, lesson_id: int) -> dict | None:
    run = session.get(SESSION_KEY)
    if run and run["lesson_id"] == lesson_id:
        return run
    return None


def current_exercise(run: dict) -> Exercise | None:
    if run["pos"] >= len(run["queue"]):
        return None
    return Exercise.objects.filter(id=run["queue"][run["pos"]]).first()


def progress_percent(run: dict) -> int:
    total = len(run["queue"]) or 1
    return round(100 * run["pos"] / total)


def is_failed(run: dict) -> bool:
    return run["hearts"] <= 0


def is_finished(run: dict) -> bool:
    return run["pos"] >= len(run["queue"])


def match_pairs(given: str) -> set[tuple[str, str]] | None:
    """Пары из ответа на «Найди пары»: JSON-список [[удмуртское, русское], ...]."""
    try:
        pairs = json.loads(given)
        return {(left, right) for left, right in pairs}
    except (TypeError, ValueError):
        return None


def submit(session, run: dict, exercise: Exercise, given: str, match_mistakes: int = 0) -> Feedback:
    """Проверяет ответ на текущее упражнение и обновляет состояние прохождения.

    match_mistakes — сколько неверных пар игрок выбрал, пока собирал «Найди пары».
    """
    if exercise.kind == Exercise.Kind.MATCH:
        expected = {(left, right) for left, right in exercise.options}
        verdict = Verdict.CORRECT if match_pairs(given) == expected else Verdict.WRONG
        correct = ", ".join(f"{left} — {right}" for left, right in exercise.options)
    else:
        verdict = check_answer(given, exercise.accepted_answers)
        correct = exercise.accepted_answers[0] if exercise.accepted_answers else ""

    if not run["answered"]:
        run["answered"] = True
        if exercise.kind == Exercise.Kind.MATCH:
            run["mistakes"] += max(match_mistakes, 0)
        first_try = exercise.id not in run["retried"]
        if verdict == Verdict.WRONG:
            run["hearts"] -= 1
            run["mistakes"] += 1
            if first_try:
                run["queue"].append(exercise.id)
                run["retried"].append(exercise.id)
        elif first_try:
            run["xp"] += settings.GAME["XP_PER_CORRECT"]
        session.modified = True

    return Feedback(verdict=verdict, correct_answer=correct)


def advance(session, run: dict) -> None:
    run["pos"] += 1
    run["answered"] = False
    session.modified = True


@transaction.atomic
def finish(session, user, run: dict) -> dict:
    """Сохраняет результат, начисляет опыт и стрик. Возвращает данные для экрана итогов."""
    xp = run["xp"] + settings.GAME["XP_LESSON_BONUS"]
    replay = LessonResult.objects.filter(user=user, lesson_id=run["lesson_id"]).exists()
    if replay:
        xp //= 2
    LessonResult.objects.create(
        user=user, lesson_id=run["lesson_id"], xp=xp, mistakes=run["mistakes"]
    )
    user.profile.register_activity(xp)
    result = {
        "lesson_id": run["lesson_id"],
        "xp": xp,
        "mistakes": run["mistakes"],
        "streak": user.profile.streak,
        "replay": replay,
    }
    session[RESULT_KEY] = result
    session.pop(SESSION_KEY, None)
    return result


def shuffled(items: list) -> list:
    items = list(items)
    random.shuffle(items)
    return items
