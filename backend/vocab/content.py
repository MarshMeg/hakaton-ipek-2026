"""Весь словарь одним JSON-документом. Его читают игры на клиенте — и онлайн, и из офлайн-снимка."""

import hashlib
import json

from .models import Fact, SortingSet, Topic, Word


def word_data(word: Word) -> dict:
    """Одно слово для /content.json. Необязательные поля (картинка, звук, эмодзи и т. д.)
    попадают в JSON, только если они заполнены."""
    data = {"id": word.id, "topic": word.topic.slug, "udm": word.udm, "ru": word.ru}
    optional = {
        "alt": word.alt,
        "tr": word.transcription,
        "emoji": word.emoji,
        "color": word.color,
        "number": word.number,
        "img": word.image_url,
        "audio": word.audio_url,
    }
    data.update({k: v for k, v in optional.items() if v not in ("", None)})
    return data


def build_content() -> dict:
    """Собирает весь словарь: темы, слова, наборы для «Сортировки», факты и версию."""
    topics = [
        {
            "slug": t.slug,
            "title": t.title,
            "title_udm": t.title_udm,
            "icon": t.icon,
            "kind": t.kind,
            # Если семейство не задано, тема сама себе семейство (для «Найди лишнее»).
            "family": t.family or t.slug,
        }
        for t in Topic.objects.all()
    ]
    words = [word_data(w) for w in Word.objects.select_related("topic")]
    content = {
        "topics": topics,
        "words": words,
        "sorting": [{"title": s.title, "groups": s.groups} for s in SortingSet.objects.all()],
        "facts": list(Fact.objects.values_list("text", flat=True)),
    }
    # Версия зависит только от содержимого — по ней видно, что словарь изменился.
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    content["version"] = hashlib.sha256(raw).hexdigest()[:12]
    return content
