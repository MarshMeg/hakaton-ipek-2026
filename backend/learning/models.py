from django.conf import settings
from django.db import models

from courses.models import Lesson


class LessonResult(models.Model):
    """Факт прохождения урока игроком (урок можно проходить повторно)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_results"
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="results")
    xp = models.PositiveIntegerField("опыт", default=0)
    mistakes = models.PositiveIntegerField("ошибок", default=0)
    completed_at = models.DateTimeField("пройден", auto_now_add=True)

    class Meta:
        ordering = ["-completed_at"]
        verbose_name = "результат урока"
        verbose_name_plural = "результаты уроков"

    def __str__(self):
        return f"{self.user} — {self.lesson} (+{self.xp} XP)"
