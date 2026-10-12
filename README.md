# Вотэс — учим удмуртский играя

Мобильная игра для детей в стиле Duolingo для изучения удмуртского языка.
Проект для хакатона «Удмуртский ИТ-класс „Вотэс“» (направление «Мобильная разработка»).

<p>
  <img src="docs/screenshots/home.png" width="180">
  <img src="docs/screenshots/choice.png" width="180">
  <img src="docs/screenshots/keyboard.png" width="180">
  <img src="docs/screenshots/result.png" width="180">
</p>

## Что умеет
- **Карта курса**: разделы и уроки; следующий урок открывается после прохождения предыдущего.
- **4 типа упражнений**: выбор перевода, ввод с клавиатуры, сборка фразы из слов, сопоставление пар.
- **Удмуртские буквы Ӝ Ӟ Ӥ Ӧ Ӵ**: экранная панель для ввода. Если вместо «ӧ» написать «о», ответ
  засчитывается как «почти верно», и игра показывает правильное написание.
- **Игровая механика**: 5 сердечек, опыт (XP), серия дней подряд, повтор ошибок в конце урока,
  мгновенная обратная связь.
- **Без регистрации**: играть можно сразу как гость, а регистрация сохраняет прогресс.
- **Админка** `/admin`: слова, уроки, аудио и картинки редактируются без программиста.

## Стек
| Слой | Технологии |
|---|---|
| Backend | Python 3.12, Django 5.2, gunicorn, whitenoise |
| Frontend | Django Templates, HTMX, Alpine.js, Tailwind CSS (брендбук в `backend/tailwind.config.js`) |
| Данные | PostgreSQL 16, MinIO (S3) для аудио и картинок |
| Мобильное приложение | Flutter (Dart) + `webview_flutter` |
| Инфраструктура | Docker Compose, GitHub Actions (тесты, линтер, сборка APK) |

Подробнее: [docs/architecture.md](docs/architecture.md).

## Быстрый запуск (Docker)
Нужен только Docker.

```bash
cp .env.example .env          # необязательно: без .env используются значения по умолчанию
docker compose up --build
```

| Адрес | Что там |
|---|---|
| http://localhost:8000 | игра (откройте в мобильном режиме браузера) |
| http://localhost:8000/admin | админка контента (логин `admin` / пароль `admin12345`) |
| http://localhost:9001 | консоль MinIO (`minioadmin` / `minioadmin`) |

При первом старте автоматически применяются миграции, загружается стартовый курс из
`backend/seeds/content.yaml` и создаётся администратор.

## Запуск без Docker (для разработки)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed
python manage.py runserver 0.0.0.0:8000
```
Без переменной `DATABASE_URL` используется SQLite, без `USE_S3=1` медиа хранятся в `backend/media/`.

## Android-приложение
**Скачать APK:** https://github.com/MarshMeg/hakaton-ipek-2026/releases/latest/download/votes.apk

APK собирается в GitHub Actions при каждом push в `main` и публикуется в
[Releases](https://github.com/MarshMeg/hakaton-ipek-2026/releases). Приложение открывает сервер
`https://hakaton.marshmeg.ru`; адрес можно поменять в самом приложении (экран «Нет связи с сервером»).

Сборка вручную — см. [mobile/README.md](mobile/README.md):
```bash
cd mobile
flutter create --platforms=android --org ru.votes .
flutter run --dart-define=SERVER_URL=http://10.0.2.2:8000   # локальный сервер из эмулятора
```

## Тесты и линтер
```bash
cd backend
pytest
ruff check . && ruff format --check .
```

## Изменение стилей
CSS собирается [standalone-версией Tailwind](https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17)
(Node.js не нужен), готовый `static/css/app.css` лежит в репозитории:
```bash
cd backend
./tailwindcss -i static/css/input.css -o static/css/app.css --minify --watch
```

## Контент
Курс описывается в `backend/seeds/content.yaml` (формат описан в начале файла) и загружается командой
`python manage.py seed --reset`. Также его можно редактировать в админке.

> ⚠️ Стартовые слова и фразы демонстрационные. Перед сдачей их нужно сверить с носителем языка
> или с материалами кейса.

## Структура
```
backend/            Django-проект
  config/           настройки, URL
  courses/          контент курса: модели, админка, команда seed
  learning/         игра: экраны урока, проверка ответов, логика урока
  accounts/         игроки: гостевой режим, регистрация, XP и стрик
  templates/        HTML-шаблоны (HTMX + Alpine.js)
  static/           CSS, шрифты с удмуртскими буквами, htmx/alpine
  seeds/            стартовый контент
  tests/            pytest
mobile/             Flutter-приложение (WebView)
docs/               архитектура, скриншоты
```
