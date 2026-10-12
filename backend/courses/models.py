"""Контент курса: Курс → Юнит → Урок → Упражнение. Редактируется через Django Admin."""

from django.db import models


class Course(models.Model):
    title = models.CharField("название", max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField("описание", blank=True)

    class Meta:
        verbose_name = "курс"
        verbose_name_plural = "курсы"

    def __str__(self):
        return self.title


class Unit(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="units")
    title = models.CharField("название", max_length=200)
    # Заголовок по-удмуртски, показывается рядом с русским.
    title_udm = models.CharField("название (удм.)", max_length=200, blank=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "раздел"
        verbose_name_plural = "разделы"

    def __str__(self):
        return f"{self.course} / {self.title}"


class Lesson(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField("название", max_length=200)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "урок"
        verbose_name_plural = "уроки"

    def __str__(self):
        return self.title


class Exercise(models.Model):
    """Одно задание урока. Поля `options` и `answer` трактуются в зависимости от типа."""

    class Kind(models.TextChoices):
        # options: список вариантов; answer: правильный вариант
        CHOICE = "choice", "Выбор перевода"
        # answer: правильный перевод (можно несколько через «|»)
        TYPE = "type", "Ввод с клавиатуры"
        # options: слова-плитки (правильные + лишние); answer: собранная фраза
        ASSEMBLE = "assemble", "Сборка фразы"
        # options: список пар [["удм", "рус"], ...]; answer не используется
        MATCH = "match", "Сопоставление пар"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="exercises")
    kind = models.CharField("тип", max_length=16, choices=Kind.choices)
    prompt = models.CharField("задание / слово", max_length=300)
    answer = models.CharField("правильный ответ", max_length=300, blank=True)
    options = models.JSONField("варианты", default=list, blank=True)
    hint = models.CharField("подсказка", max_length=300, blank=True)
    audio = models.FileField("аудио", upload_to="audio/", blank=True)
    image = models.FileField("картинка", upload_to="images/", blank=True)
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "упражнение"
        verbose_name_plural = "упражнения"

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.prompt}"

    @property
    def accepted_answers(self) -> list[str]:
        """Все допустимые варианты ответа (в админке пишутся через «|»)."""
        return [a.strip() for a in self.answer.split("|") if a.strip()]
