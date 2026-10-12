"""Игровой профиль: опыт, серия дней (стрик). Гость — обычный User с флагом is_guest."""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    is_guest = models.BooleanField("гость", default=True)
    xp = models.PositiveIntegerField("опыт", default=0)
    streak = models.PositiveIntegerField("серия дней", default=0)
    last_active = models.DateField("последнее занятие", null=True, blank=True)
    avatar = models.ImageField("аватарка", upload_to="avatars/", blank=True)
    # В таблице лидеров другие игроки видят вместо имени и аватарки «Аноним».
    leaderboard_anonymous = models.BooleanField("анонимно в таблице лидеров", default=False)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return self.user.get_username()

    @property
    def display_name(self) -> str:
        """Имя для показа в игре: «Айно К.». Вход — по username, он показывается, если имени нет."""
        name, family = self.user.first_name.strip(), self.user.last_name.strip()
        if not name:
            return self.user.get_username()
        return f"{name} {family[0].upper()}." if family else name

    def register_activity(self, xp_gained: int) -> None:
        """Начисляет опыт и продлевает стрик, если сегодня ещё не занимались."""
        today = timezone.localdate()
        if self.last_active != today:
            if self.last_active == today - timedelta(days=1):
                self.streak += 1
            else:
                self.streak = 1
            self.last_active = today
        self.xp += xp_gained
        self.save(update_fields=["xp", "streak", "last_active"])
