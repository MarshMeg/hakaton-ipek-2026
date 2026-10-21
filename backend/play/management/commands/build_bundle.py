"""Офлайн-снимок приложения: все страницы, статика, словарь и медиа.

Снимок кладётся в APK (mobile/assets/bundle/), и Android-приложение отвечает на запросы
WebView из него, не обращаясь к сети. На сервере тот же снимок лежит в BUNDLE_DIR и отдаётся
по /bundle/ — так телефон узнаёт о новой версии и докачивает только изменившиеся файлы.

Формат:
    manifest.json   {"version": "...", "built": <мс>,
                     "files": {"/learn/": {"sha": "...", "type": "...", "size": N}}}
    blobs/<sha256>  содержимое файлов; имя — хэш, поэтому одинаковые файлы хранятся один раз,
                    а уже скачанные не качаются повторно.
"""

import hashlib
import json
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.urls import reverse

from play.games import GAMES
from play.mime import guess_type
from vocab.models import Topic, Word, media_url

# Статика, которая не нужна на телефоне.
SKIP_STATIC_PREFIXES = ("admin/", "css/input.css")
SKIP_STATIC_SUFFIXES = (".gz", ".br")
VERSION_LENGTH = 16  # символов sha256 в версии снимка
KEEP_IN_BLOBS = ".gitkeep"  # держит пустую папку blobs/ в git


def page_urls() -> list[str]:
    """Все адреса страниц, которые попадут в снимок: разделы, каждая тема и каждая игра.
    Новый экран надо добавить сюда, иначе офлайн его не будет."""
    urls = [
        reverse("play:home"),
        reverse("vocab:topics"),
        reverse("vocab:content"),
        reverse("play:games"),
        reverse("play:profile"),
        reverse("play:settings"),
        reverse("play:report"),
    ]
    urls += [
        reverse("vocab:topic", args=[slug]) for slug in Topic.objects.values_list("slug", flat=True)
    ]
    urls += [reverse("play:game", args=[g.slug]) for g in GAMES]
    return urls


def static_files():
    """(url, абсолютный путь). В проде с ManifestStaticFilesStorage шаблоны ссылаются на
    файлы с хэшем в имени — берём их из собранного collectstatic; иначе — исходники."""
    prefix = "/" + settings.STATIC_URL.strip("/") + "/"
    manifest = Path(settings.STATIC_ROOT) / "staticfiles.json"
    if manifest.exists() and not settings.DEBUG:
        files = _collected_static(manifest)
    else:
        files = _source_static()
    for rel, path in files:
        yield prefix + rel, path


def _collected_static(manifest: Path):
    # (имя файла с хэшем, путь) из собранного collectstatic, по алфавиту исходных имён.
    static_root = manifest.parent
    paths = json.loads(manifest.read_text(encoding="utf-8"))["paths"]
    for rel, hashed in sorted(paths.items()):
        if _wanted(rel):
            yield hashed, static_root / hashed


def _source_static():
    # (имя файла, путь) из исходников. Один файл может найтись несколькими finder — берём первый.
    seen = set()
    for finder in finders.get_finders():
        for rel, storage in finder.list([]):
            rel = rel.replace("\\", "/")
            if rel in seen or not _wanted(rel):
                continue
            seen.add(rel)
            yield rel, Path(storage.path(rel))


def _wanted(rel: str) -> bool:
    # Пропускаем статику админки, исходник Tailwind и сжатые копии от whitenoise.
    return not rel.startswith(SKIP_STATIC_PREFIXES) and not rel.endswith(SKIP_STATIC_SUFFIXES)


def pages():
    """(url, содержимое, Content-Type) каждой страницы из page_urls()."""
    client = Client()
    for url in page_urls():
        # Страницы рендерим «изнутри», поэтому ALLOWED_HOSTS тут не важен.
        with override_settings(ALLOWED_HOSTS=["*"]):
            response = client.get(url)
        if response.status_code != 200:
            raise CommandError(f"{url}: HTTP {response.status_code}")
        yield url, response.content, response["Content-Type"]


def media_files():
    """(url, содержимое, Content-Type) картинок и звуков слов, которые есть в хранилище."""
    for word in Word.objects.all():
        for field in (word.image, word.audio):
            if field and default_storage.exists(field.name):
                with default_storage.open(field.name) as fh:
                    yield media_url(field), fh.read(), guess_type(field.name)


def bundle_version(files: dict[str, dict]) -> str:
    """Версия — хэш от списка «url sha»: меняется, только если поменялся какой-то файл."""
    lines = "\n".join(f"{url} {files[url]['sha']}" for url in sorted(files))
    return hashlib.sha256(lines.encode()).hexdigest()[:VERSION_LENGTH]


def remove_unused_blobs(blobs: Path, files: dict[str, dict]):
    used = {f["sha"] for f in files.values()}
    for blob in blobs.iterdir():
        if blob.name not in used and blob.name != KEEP_IN_BLOBS:
            blob.unlink()


def write_manifest(out: Path, manifest: dict):
    # Через .tmp и move: сервер не отдаст недописанный манифест.
    tmp = out / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.move(tmp, out / "manifest.json")


class Command(BaseCommand):
    help = "Собирает офлайн-снимок приложения (страницы, статика, словарь, медиа)."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(settings.BUNDLE_DIR), help="папка снимка")

    def handle(self, *args, **opts):
        out = Path(opts["out"])
        blobs = out / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        files: dict[str, dict] = {}

        # Кладёт содержимое в blobs/<sha> (если такого ещё нет) и запоминает url → sha.
        def add(url: str, data: bytes, content_type: str):
            sha = hashlib.sha256(data).hexdigest()
            blob = blobs / sha
            if not blob.exists():
                blob.write_bytes(data)
            files[url] = {"sha": sha, "type": content_type, "size": len(data)}

        for url, data, content_type in pages():
            add(url, data, content_type)
        for url, path in static_files():
            add(url, path.read_bytes(), guess_type(path.name))
        for url, data, content_type in media_files():
            add(url, data, content_type)

        version = bundle_version(files)
        # built — время сборки: приложение выбирает из снимка в APK и скачанного тот, что новее.
        manifest = {
            "version": version,
            "built": int(time.time() * 1000),
            "files": dict(sorted(files.items())),
        }
        # Старые блобы удаляем, а манифест пишем последним и атомарно: пока идёт сборка,
        # сервер продолжает отдавать прежнюю целую версию.
        remove_unused_blobs(blobs, files)
        write_manifest(out, manifest)

        size = sum(f["size"] for f in files.values()) / 1024 / 1024
        self.stdout.write(
            self.style.SUCCESS(f"Снимок {version}: {len(files)} файлов, {size:.1f} МБ → {out}")
        )
