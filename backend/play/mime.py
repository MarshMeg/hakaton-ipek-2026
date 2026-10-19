"""Тип содержимого по имени файла — один и тот же для /media/ и для манифеста офлайн-снимка.

mimetypes берёт таблицу из ОС и из своей версии Python: в Docker-образе (python:3.12, без
/etc/mime.types) он не знает .webp и отдаёт None. Поэтому типы файлов, которые есть
в приложении, заданы здесь явно, а mimetypes — только запасной вариант."""

import mimetypes
from pathlib import PurePath

KNOWN = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".woff2": "font/woff2",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
}


def guess_type(name: str) -> str:
    """Например, "words/bear.webp" → "image/webp"; текстовым типам дописывается кодировка."""
    ext = PurePath(name).suffix.lower()
    content_type = KNOWN.get(ext) or mimetypes.guess_type(name)[0]
    if content_type and content_type.startswith("text/"):
        return content_type + "; charset=utf-8"
    return content_type or "application/octet-stream"
