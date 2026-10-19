"""Загрузка словаря из seeds/vocab.yaml (и медиа из seeds/media/).

Команда идемпотентна: темы ищутся по slug, слова — по (тема, udm), поэтому у существующих слов
сохраняется id и прогресс игроков не теряется. Правки, сделанные в админке, перезаписываются
значениями из файла только с --update.
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from vocab.models import Fact, SortingSet, Topic, Word

SEEDS_DIR = Path(settings.BASE_DIR) / "seeds"
WORD_FIELDS = ("ru", "alt", "transcription", "emoji", "color", "number", "needs_check")
# Эти поля, если в базе они пусты, а в файле появились позже, заполняются и без --update.
FILL_EMPTY = ("alt", "transcription", "emoji", "color")


class Command(BaseCommand):
    help = "Загружает словарь из seeds/vocab.yaml. Уже загруженные слова пропускает."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(SEEDS_DIR / "vocab.yaml"))
        parser.add_argument(
            "--update", action="store_true", help="перезаписать существующие слова из файла"
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        data = yaml.safe_load(Path(opts["file"]).read_text(encoding="utf-8"))
        update = opts["update"]
        created = 0
        topic_slugs = set()

        for t_order, t in enumerate(data["topics"]):
            topic, _ = Topic.objects.update_or_create(
                slug=t["slug"],
                defaults={
                    "title": t["title"],
                    "title_udm": t.get("title_udm", ""),
                    "icon": t.get("icon", ""),
                    "kind": t.get("kind", Topic.Kind.WORDS),
                    "family": t.get("family", ""),
                    "order": t_order,
                },
            )
            topic_slugs.add(topic.slug)
            for w_order, w in enumerate(t["words"]):
                values = {f: w.get(f, None if f == "number" else "") for f in WORD_FIELDS}
                values["order"] = w_order
                word, is_new = Word.objects.get_or_create(
                    topic=topic, udm=w["udm"], defaults=values
                )
                created += is_new
                if update and not is_new:
                    for field, value in values.items():
                        setattr(word, field, value)
                if is_new or update:
                    self._attach_media(word, w)
                    word.save()
                else:
                    # Картинки, звук и поля из FILL_EMPTY, добавленные в файл позже: без --update
                    # докладываются только туда, где их ещё нет, — правки в админке не трогаем.
                    filled = [f for f in FILL_EMPTY if values[f] and not getattr(word, f)]
                    for field in filled:
                        setattr(word, field, values[field])
                    if self._attach_media(word, w, only_missing=True) or filled:
                        word.save()

        for s_order, s in enumerate(data.get("sorting", [])):
            for group in s["groups"]:
                unknown = set(group["topics"]) - topic_slugs
                if unknown:
                    raise CommandError(f"«{s['title']}»: неизвестные темы {sorted(unknown)}")
            SortingSet.objects.update_or_create(
                title=s["title"], defaults={"groups": s["groups"], "order": s_order}
            )

        # Факты — простой список, его проще перезаливать целиком.
        for fact in data.get("facts", []):
            # Факт с «: » без кавычек YAML читает как словарь — лучше упасть, чем показать {…}.
            if not isinstance(fact, str):
                raise CommandError(f"Факт должен быть строкой (возьми в кавычки): {fact!r}")
        if data.get("facts") and (update or not Fact.objects.exists()):
            Fact.objects.all().delete()
            Fact.objects.bulk_create(
                Fact(text=text, order=i) for i, text in enumerate(data["facts"])
            )

        total = Word.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f"Словарь загружен: новых слов {created}, всего {total}.")
        )

    def _attach_media(self, word, w, only_missing=False) -> bool:
        # Файлы сохраняются через storage — локально в media/ или в MinIO, если USE_S3=1.
        attached = False
        for field in ("image", "audio"):
            if not w.get(field):
                continue
            path = SEEDS_DIR / "media" / w[field]
            current = getattr(word, field)
            if not only_missing or not current or _is_stale_seed_copy(current, path):
                with path.open("rb") as fh:
                    getattr(word, field).save(path.name, File(fh), save=False)
                attached = True
        return attached


def _is_stale_seed_copy(current, path: Path) -> bool:
    """Файл когда-то загружен из seeds/media/, а в репозитории его с тех пор заменили.

    Копию узнаём по имени: storage сохраняет «hen.webp» как есть или как «hen_<суффикс>.webp».
    Загруженное через админку называется иначе и не трогается. Содержимое сравниваем по размеру —
    это один HEAD-запрос к MinIO, а не скачивание файла.
    """
    name = Path(current.name)
    if name.suffix != path.suffix or not (
        name.stem == path.stem or name.stem.startswith(f"{path.stem}_")
    ):
        return False
    try:
        return current.storage.size(current.name) != path.stat().st_size
    except OSError:
        return True
