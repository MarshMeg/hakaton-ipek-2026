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

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return self.user.get_username()

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
