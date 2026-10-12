# Архитектура «Вотэс»

```
Android (Flutter, WebView)
        │  HTTP(S): HTML, CSS, JS (HTMX + Alpine.js)
        ▼
web: Django + gunicorn ── страницы игры, /admin для контента
        │                         │
        │ ORM                     │ django-storages (аудио, картинки)
        ▼                         ▼
   PostgreSQL                 MinIO (S3) ◀── браузер/WebView скачивает медиа напрямую
```

## Модель данных
- `courses`: **Course → Unit → Lesson → Exercise** (типы: choice, type, assemble, match).
- `accounts.Profile`: опыт (XP), стрик, флаг гостя.
- `learning.LessonResult`: факт прохождения урока.

## Как проходит урок
1. `lesson_start` кладёт в сессию очередь упражнений и 5 сердечек.
2. Каждый ответ уходит HTMX-запросом в `lesson_answer` → `answer_check.check_answer`
   (верно / почти верно / неверно) → перерисовывается только тело урока.
3. Ошибка: −1 сердечко, упражнение повторяется в конце урока.
4. Когда очередь закончилась, `finish` начисляет XP и стрик и ведёт на экран итогов.

Ключевые файлы: `backend/learning/services/lesson_engine.py`, `backend/learning/services/answer_check.py`,
`backend/learning/views.py`, `backend/templates/learning/partials/`.
