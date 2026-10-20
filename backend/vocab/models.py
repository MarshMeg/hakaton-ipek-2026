"""Словарь: темы и слова. Из них строятся карточки раздела «Обучение» и раунды всех игр.

Редактируется через Django Admin или загружается из seeds/vocab.yaml командой `seed`.
После изменения контента нужно пересобрать снимок для офлайна: `manage.py build_bundle`.
"""

from django.conf import settings
from django.db import models


def media_url(field) -> str:
    """Ссылка на файл через наш же сервер (/media/…), а не на MinIO: так один и тот же адрес
    работает в браузере и попадает в офлайн-снимок (см. play.views.media)."""
    if not field:
        return ""
    return "/" + settings.MEDIA_URL.strip("/") + "/" + field.name


class Topic(models.Model):
    class Kind(models.TextChoices):
        # Как показывать «картинку» слова, если файла с изображением нет.
        WORDS = "words", "Слова (эмодзи или картинка)"
        NUMBERS = "numbers", "Числа (показываем цифру)"
        COLORS = "colors", "Цвета (показываем цветной круг)"
        PHRASES = "phrases", "Фразы (не участвуют в «Собери слово»)"

    slug = models.SlugField(unique=True)
    title = models.CharField("название", max_length=100)
    # Название по-удмуртски. Заполнять только проверенным переводом.
    title_udm = models.CharField("название (удм.)", max_length=100, blank=True)
    icon = models.CharField("иконка (эмодзи)", max_length=16, blank=True)
    kind = models.CharField("тип", max_length=16, choices=Kind.choices, default=Kind.WORDS)
    # Близкие по смыслу темы (овощи и еда, дикие и домашние животные) в «Найди лишнее»
    # не смешиваются: иначе «лишнее» слово было бы спорным.
    family = models.SlugField("семейство тем", blank=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "тема"
        verbose_name_plural = "темы"

    def __str__(self):
        return self.title


class Word(models.Model):
    """Слово или фраза. id слова — ключ в сохранениях игроков (блок words), поэтому слова
    не надо удалять и создавать заново: прогресс по ним потеряется."""

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="words")
    udm = models.CharField("по-удмуртски", max_length=120)
    ru = models.CharField("перевод", max_length=120)
    # Другие формы того же слова, например «курегпуз» для «кукей».
    alt = models.CharField("варианты", max_length=120, blank=True)
    transcription = models.CharField("произношение", max_length=120, blank=True)
    emoji = models.CharField("эмодзи", max_length=16, blank=True)
    # Для темы «Цвета»: #rrggbb.
    color = models.CharField("цвет", max_length=7, blank=True)
    # Для темы «Числа»: само число.
    number = models.PositiveSmallIntegerField("число", null=True, blank=True)
    image = models.FileField("картинка", upload_to="words/", blank=True)
    audio = models.FileField("аудио", upload_to="audio/", blank=True)
    # Требует проверки носителем языка (показывается в админке).
    needs_check = models.CharField("что проверить", max_length=200, blank=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["topic__order", "order", "id"]
        verbose_name = "слово"
        verbose_name_plural = "слова"
        constraints = [
            models.UniqueConstraint(fields=["topic", "udm"], name="unique_word_in_topic"),
        ]

    def __str__(self):
        return f"{self.udm} — {self.ru}"

    # Ссылки для шаблонов и /content.json (пустая строка, если файла нет).
    @property
    def image_url(self) -> str:
        return media_url(self.image)

    @property
    def audio_url(self) -> str:
        return media_url(self.audio)


class SortingSet(models.Model):
    """Набор для игры «Сортировка»: группы, каждая собирается из слов указанных тем."""

    title = models.CharField("название", max_length=100)
    # [{"label": "Дикие", "topics": ["wild-animals"]}, ...]
    groups = models.JSONField("группы", default=list)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "набор для сортировки"
        verbose_name_plural = "наборы для сортировки"

    def __str__(self):
        return self.title


class Fact(models.Model):
    """Факт об удмуртском языке для экрана «Профиль»."""

    text = models.TextField("текст")
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "факт о языке"
        verbose_name_plural = "факты о языке"

    def __str__(self):
        return self.text[:60]
