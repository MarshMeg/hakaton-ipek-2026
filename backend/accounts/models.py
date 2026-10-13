"""Игровой профиль: опыт, серия дней (стрик). Гость — обычный User с флагом is_guest."""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
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

    def register_activity(self) -> None:
        """Продлевает стрик, если сегодня ещё не занимались, и обновляет суммарный опыт."""
        from learning.models import PlayerXp  # learning зависит от accounts, не наоборот

        today = timezone.localdate()
        if self.last_active != today:
            if self.last_active == today - timedelta(days=1):
                self.streak += 1
            else:
                self.streak = 1
            self.last_active = today
        # Опыт считает БД (представление learning_player_xp) — тем же запросом, что и стрик.
        total_xp = PlayerXp.objects.filter(user_id=OuterRef("user_id")).values("xp")
        Profile.objects.filter(pk=self.pk).update(
            streak=self.streak, last_active=self.last_active, xp=Coalesce(Subquery(total_xp), 0)
        )
        self.refresh_from_db(fields=["xp"])
