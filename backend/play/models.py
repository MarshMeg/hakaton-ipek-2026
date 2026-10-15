from django.conf import settings
from django.db import models


class Attempt(models.Model):
    """Одна попытка в игре (или просмотр карточки). Журнал только дописывается.

    Событие создаётся на телефоне, поэтому у него свой uuid: повторная отправка при
    синхронизации ничего не дублирует.
    """

    uuid = models.UUIDField(unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts"
    )
    # Без внешнего ключа: слово могут удалить из словаря, а история должна остаться.
    word_id = models.PositiveIntegerField("слово")
    game = models.CharField("игра", max_length=16)
    # None — просмотр карточки в «Обучении», а не ответ.
    correct = models.BooleanField("верно", null=True)
    ts = models.BigIntegerField("время (мс, по часам телефона)")

    class Meta:
        ordering = ["ts"]
        verbose_name = "попытка"
        verbose_name_plural = "попытки"

    def __str__(self):
        return f"{self.user} · {self.game} · слово {self.word_id}"
