"""Облачный профиль игрока. Основной профиль живёт на телефоне; здесь — копия имени и аватара,
чтобы восстановить их на новом устройстве. Сам прогресс — в play.Attempt."""

from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField("имя ребёнка", max_length=60, blank=True)
    avatar = models.CharField("аватар (эмодзи)", max_length=16, blank=True)
    # Время последней правки имени/аватара на телефоне (мс) — для разрешения конфликтов.
    updated = models.BigIntegerField("изменён", default=0)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return self.display_name or self.user.get_username()
