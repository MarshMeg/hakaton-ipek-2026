"""Раздел «Обучение»: список тем и карточки слов.

Страницы не зависят от игрока (прогресс подставляет JS на клиенте), поэтому их можно
целиком положить в офлайн-снимок.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .content import build_content
from .models import Topic


def topics(request):
    """/learn/ — плитки тем. Сколько слов просмотрено и выучено, дорисовывает Alpine."""
    items = Topic.objects.all()
    return render(request, "vocab/topics.html", {"topics": items})


def topic(request, slug):
    """/learn/<slug>/ — карточки слов одной темы."""
    item = get_object_or_404(Topic, slug=slug)
    return render(request, "vocab/topic.html", {"topic": item, "words": item.words.all()})


def content_json(request):
    """/content.json — словарь для игр (см. content.py). ensure_ascii=False — удмуртские
    буквы пишутся в JSON как есть, без экранирования."""
    return JsonResponse(build_content(), json_dumps_params={"ensure_ascii": False})
