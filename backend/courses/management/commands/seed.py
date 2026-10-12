"""Загрузка контента курса из seeds/content.yaml (и медиа из seeds/media/)."""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from courses.models import Course, Exercise, Lesson, Unit

SEEDS_DIR = Path(settings.BASE_DIR) / "seeds"


class Command(BaseCommand):
    help = "Загружает курс из seeds/content.yaml. Без --reset пропускает уже загруженный курс."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(SEEDS_DIR / "content.yaml"))
        parser.add_argument("--reset", action="store_true", help="удалить курс и загрузить заново")

    @transaction.atomic
    def handle(self, *args, **opts):
        data = yaml.safe_load(Path(opts["file"]).read_text(encoding="utf-8"))
        course_data = data["course"]

        existing = Course.objects.filter(slug=course_data["slug"])
        if existing.exists():
            if not opts["reset"]:
                self.stdout.write("Курс уже загружен — пропускаю (используйте --reset).")
                return
            existing.delete()

        course = Course.objects.create(**course_data)
        n_exercises = 0
        for u_order, unit_data in enumerate(data["units"]):
            unit = Unit.objects.create(
                course=course,
                title=unit_data["title"],
                title_udm=unit_data.get("title_udm") or "",
                order=u_order,
            )
            for l_order, lesson_data in enumerate(unit_data["lessons"]):
                lesson = Lesson.objects.create(unit=unit, title=lesson_data["title"], order=l_order)
                for e_order, ex in enumerate(lesson_data["exercises"]):
                    self._create_exercise(lesson, e_order, ex)
                    n_exercises += 1

        message = f"Загружен курс «{course}»: {n_exercises} упражнений."
        self.stdout.write(self.style.SUCCESS(message))

    def _create_exercise(self, lesson, order, ex):
        kind = ex["kind"]
        if kind not in Exercise.Kind.values:
            raise CommandError(f"Неизвестный тип упражнения: {kind}")
        if kind == Exercise.Kind.CHOICE and ex["answer"] not in ex["options"]:
            raise CommandError(f"Ответ «{ex['answer']}» отсутствует среди вариантов")
        exercise = Exercise(
            lesson=lesson,
            kind=kind,
            prompt=ex["prompt"],
            answer=ex.get("answer", ""),
            options=ex.get("options", []),
            hint=ex.get("hint", ""),
            order=order,
        )
        # Файлы сохраняются через storage — локально в media/ или в MinIO, если USE_S3=1.
        for field in ("audio", "image"):
            if ex.get(field):
                path = SEEDS_DIR / "media" / ex[field]
                with path.open("rb") as fh:
                    getattr(exercise, field).save(path.name, File(fh), save=False)
        exercise.save()
