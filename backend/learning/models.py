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
    score = models.PositiveIntegerField("счёт", default=0)
    accuracy = models.FloatField("точность", default=0)
    max_combo = models.PositiveIntegerField("макс. комбо", default=0)
    mistakes = models.PositiveIntegerField("ошибок", default=0)
    completed_at = models.DateTimeField("пройден", auto_now_add=True)

    class Meta:
        ordering = ["-completed_at"]
        indexes = [models.Index(fields=["user", "lesson"], name="lessonresult_user_lesson")]
        verbose_name = "результат урока"
        verbose_name_plural = "результаты уроков"

    def __str__(self):
        return f"{self.user} — {self.lesson} (+{self.xp} XP)"


class PlayerXp(models.Model):
    """Суммарный опыт игрока — представление БД learning_player_xp (создаётся миграцией).

    Как pp в osu!: лучшие результаты по каждому уроку по убыванию с весами 0.95^i
    плюс бонус за число пройденных уроков. Формула живёт только в SQL представления;
    Profile.xp — её кэш, обновляется в Profile.register_activity().
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        primary_key=True,
        related_name="player_xp",
    )
    xp = models.PositiveIntegerField("опыт")
    lessons_done = models.PositiveIntegerField("пройдено уроков")

    class Meta:
        managed = False
        db_table = "learning_player_xp"
        verbose_name = "суммарный опыт"
        verbose_name_plural = "суммарный опыт"

    def __str__(self):
        return f"{self.user} — {self.xp} XP"
