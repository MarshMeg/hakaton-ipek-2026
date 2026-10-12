"""Какие уроки игрок прошёл и какие ему открыты.

Урок открыт, если он пройден или пройден предыдущий в порядке курса (как дорожка в Duolingo).
Первый урок курса открыт всегда.
"""

from courses.models import Lesson
from learning.models import LessonResult


def lesson_states(user, course_id: int) -> dict[int, dict]:
    """{id урока: {"done": пройден, "open": открыт}} — для всех уроков курса."""
    lesson_ids = Lesson.objects.filter(unit__course_id=course_id).order_by(
        "unit__order", "unit_id", "order", "id"
    )
    done_ids = set(LessonResult.objects.filter(user=user).values_list("lesson_id", flat=True))
    states, unlocked = {}, True
    for lesson_id in lesson_ids.values_list("id", flat=True):
        done = lesson_id in done_ids
        states[lesson_id] = {"done": done, "open": unlocked or done}
        unlocked = done
    return states


def is_lesson_open(user, lesson: Lesson) -> bool:
    return lesson_states(user, lesson.unit.course_id)[lesson.id]["open"]
