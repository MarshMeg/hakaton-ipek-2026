"""Очки за одно прохождение урока (по мотивам osu!): оценка ответа, комбо, точность, опыт.

Суммарный опыт игрока (взвешенная сумма лучших результатов) считает сама БД —
представление learning_player_xp, см. модель PlayerXp.
"""

from django.conf import settings

from .answer_check import Verdict


def hit_value(verdict: Verdict, first_try: bool) -> int:
    """Очки за ответ без учёта комбо: верно / почти / верно на повторе / мимо."""
    values = settings.GAME["HIT_VALUES"]
    if verdict == Verdict.WRONG:
        return 0
    if not first_try:
        return values["retry"]
    return values["correct"] if verdict == Verdict.CORRECT else values["almost"]


def combo_score(hit: int, combo: int) -> int:
    """Очки за ответ с множителем комбо (combo — длина серии до этого ответа)."""
    return round(hit * (1 + settings.GAME["COMBO_STEP"] * combo))


def max_score(total: int) -> int:
    """Счёт идеального прохождения урока из total упражнений."""
    best = settings.GAME["HIT_VALUES"]["correct"]
    return sum(combo_score(best, combo) for combo in range(total))


def accuracy(hits: dict, total: int) -> float:
    """Доля набранных очков (без комбо) от максимума, 0..1. Повторы в total не входят."""
    if not total:
        return 0.0
    return sum(hits.values()) / (settings.GAME["HIT_VALUES"]["correct"] * total)


def lesson_xp(score: int, total: int) -> int:
    """Опыт за урок: чем длиннее урок и чем ближе счёт к идеальному, тем больше."""
    if not total:
        return 0
    return max(1, round(settings.GAME["XP_PER_CORRECT"] * total * score / max_score(total)))


# Коэффициенты представления learning_player_xp (learning/migrations/0002). Здесь они нужны
# только чтобы показать игроку разбор по урокам; сам опыт по-прежнему считает БД.
XP_WEIGHT_BASE = 0.95
XP_BONUS_MAX = 100
XP_BONUS_BASE = 0.9


def xp_breakdown(user) -> dict:
    """Из чего сложился суммарный опыт: лучшие результаты по урокам с их весами и бонус.

    rows — лучший результат каждого урока по убыванию опыта: сколько опыта получено (xp),
    какой процент применился (percent) и сколько вошло в сумму (applied).
    """
    best = {}
    for result in user.lesson_results.select_related("lesson").order_by("-xp", "-completed_at"):
        best.setdefault(result.lesson_id, result)
    rows = []
    for pos, result in enumerate(best.values()):
        weight = XP_WEIGHT_BASE**pos
        rows.append(
            {
                "result": result,
                "xp": result.xp,
                "percent": round(weight * 100),
                "applied": result.xp * weight,
            }
        )
    bonus = XP_BONUS_MAX * (1 - XP_BONUS_BASE ** len(rows))
    return {
        "rows": rows,
        "bonus": bonus,
        "total": round(sum(row["applied"] for row in rows) + bonus),
    }
