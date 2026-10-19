"""Экраны приложения. Все страницы одинаковы для любого игрока: имя, опыт и статистику
подставляет JS из локального хранилища. Благодаря этому страницы попадают в офлайн-снимок
(см. management/commands/build_bundle.py) и работают без сети."""

import re

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from vocab.models import Fact, Topic

from .games import GAMES, GAMES_BY_SLUG
from .mime import guess_type


def home(request):
    return render(request, "play/home.html")


def games(request):
    return render(request, "play/games.html", {"games": GAMES})


def game(request, slug):
    item = GAMES_BY_SLUG.get(slug)
    if item is None:
        raise Http404
    return render(
        request,
        "play/game.html",
        {"game": item, "topics": Topic.objects.all(), "template": f"play/games/{slug}.html"},
    )


def profile(request):
    return render(request, "play/profile.html", {"facts": Fact.objects.all()})


def settings_page(request):
    return render(request, "play/settings.html")


def report(request):
    return render(request, "play/report.html")


@require_GET
def media(request, path):
    """Отдаёт картинки и аудио из хранилища (локальная папка или MinIO) по нашему адресу."""
    if ".." in path or not default_storage.exists(path):
        raise Http404
    return FileResponse(default_storage.open(path), content_type=guess_type(path))


_SHA = re.compile(r"^[0-9a-f]{64}$")


@require_GET
def bundle_file(request, name):
    """Файлы офлайн-снимка для обновления приложения: manifest.json и blobs/<sha256>."""
    if name != "manifest.json" and not (name.startswith("blobs/") and _SHA.match(name[6:])):
        raise Http404
    path = settings.BUNDLE_DIR / name
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open("rb"))
    # Манифест должен всегда быть свежим, а блобы не меняются никогда (имя = хэш содержимого).
    response["Cache-Control"] = (
        "no-cache" if name == "manifest.json" else "public, max-age=31536000, immutable"
    )
    return response
