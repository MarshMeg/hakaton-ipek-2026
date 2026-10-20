"""Аккаунт игрока на сервере. Прогресс хранится «сохранением» — одним JSON-документом
на аккаунт (формат v2, см. play/api.py). При синхронизации побеждает более новое сохранение
целиком, без слияния."""

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Профиль к стандартному User: тут лежит сохранение и пара полей-копий для админки.

    Создаётся при регистрации (play.api.signup), а для аккаунтов из админки — при первом
    обращении к API (get_or_create в play/api.py)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    # Копия save.profile, чтобы имя и зверёк были видны в админке. Обновляется при каждой записи.
    display_name = models.CharField("имя ребёнка", max_length=60, blank=True)
    avatar = models.CharField("аватар (эмодзи)", max_length=16, blank=True)
    # Время сохранения (мс, по часам телефона) — копия save.updated, по нему сравниваются версии.
    updated = models.BigIntegerField("изменён", default=0)
    # Само сохранение (поле не называется save: это затенило бы метод Model.save()).
    save_data = models.JSONField("сохранение", default=dict, blank=True)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return self.display_name or self.user.get_username()
