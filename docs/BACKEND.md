# Бэкенд (Django)

Справочник по `backend/`: модели, адреса, API и команды. Общая схема — в
[ARCHITECTURE.md](ARCHITECTURE.md), команды разработки и CI — в [development.md](development.md).

Python 3.12 (uv), Django 5.2, gunicorn + whitenoise. БД — PostgreSQL 16 в Docker и в проде,
SQLite без `DATABASE_URL`. Медиа — MinIO через `django-storages` при `USE_S3=1`, иначе `backend/media/`.

## Приложения

| Приложение | Что внутри |
|---|---|
| `config` | `settings.py` (всё из переменных окружения через `django-environ`), корневой `urls.py` |
| `vocab` | словарь: модели, админка, `/learn/`, `/content.json`, команда `seed` |
| `play` | экраны, `/media/`, `/bundle/`, JSON API аккаунта (`api.py`), список игр (`games.py`), команда `build_bundle` |
| `accounts` | `Profile` — сохранение прогресса аккаунта |

## Модели

### `vocab.Topic` — тема
| Поле | Тип | Назначение |
|---|---|---|
| `slug` | SlugField, unique | адрес темы `/learn/<slug>/`, ключ при `seed` |
| `title`, `title_udm` | CharField | название по-русски и по-удмуртски (второе необязательно) |
| `icon` | CharField | эмодзи темы |
| `kind` | `words` / `numbers` / `colors` / `phrases` | запасная «картинка» слова: эмодзи, цифра, цветной круг; `phrases` не участвуют в «Собери слово» и «Найди лишнее» |
| `family` | SlugField | близкие темы с одним `family` не смешиваются в «Найди лишнее»; пусто → в `/content.json` подставляется `slug` |
| `order` | int | порядок; сортировка `order, id` |

### `vocab.Word` — слово или фраза
| Поле | Назначение |
|---|---|
| `topic` | FK на `Topic` (`related_name="words"`) |
| `udm`, `ru` | слово и перевод; пара (`topic`, `udm`) уникальна |
| `alt` | другие формы слова |
| `transcription` | произношение (показывается на карточке) |
| `emoji`, `color` (`#rrggbb`), `number` | запасные варианты «картинки» |
| `image`, `audio` | FileField (`words/`, `audio/`) в хранилище по умолчанию |
| `needs_check` | что сверить с носителем языка (видно в админке) |
| `order` | порядок внутри темы |

`id` слова — ключ в сохранениях игроков, поэтому `seed` слова не пересоздаёт. Свойства
`image_url` / `audio_url` дают ссылку `/media/<имя>` (функция `media_url`), а не адрес MinIO.

### `vocab.SortingSet` и `vocab.Fact`
- `SortingSet` — набор для «Сортировки»: `title`, `groups` (JSON
  `[{"label": "Дикие", "topics": ["wild-animals"]}, …]`, в группе может быть `icon`), `order`.
- `Fact` — факт об удмуртском языке для профиля: `text`, `order`.

### `accounts.Profile`
| Поле | Назначение |
|---|---|
| `user` | OneToOne на `User` (`related_name="profile"`) |
| `save_data` | JSON-сохранение (формат — в [ARCHITECTURE.md](ARCHITECTURE.md#вход-сохранение-и-синхронизация)) |
| `updated` | копия `save.updated` (мс по часам телефона) |
| `display_name`, `avatar` | копии `save.profile.name` / `.avatar` для админки |

Миграции: по одной `0001_initial` в `accounts` и `vocab`, в `play` моделей и миграций нет. На базе, где
применены старые миграции, `migrate` ничего не делает: `0001_initial` уже отмечена применённой, а схема
совпадает с итоговой.

## Страницы

Все страницы одинаковы для любого посетителя: нет данных игрока и CSRF-токенов. Имя, опыт и статистику подставляет JS. Поэтому их можно положить в офлайн-снимок.

| Путь | View | Шаблон |
|---|---|---|
| `/` | `play.views.home` | `play/home.html` |
| `/learn/` | `vocab.views.topics` | `vocab/topics.html` |
| `/learn/<slug>/` | `vocab.views.topic` | `vocab/topic.html` (404, если темы нет) |
| `/games/` | `play.views.games` | `play/games.html` |
| `/games/<slug>/` | `play.views.game` | `play/game.html` + `play/games/<slug>.html` (404 для неизвестного slug) |
| `/profile/` | `play.views.profile` | `play/profile.html` (факты из БД) |
| `/settings/` | `play.views.settings_page` | `play/settings.html` |
| `/report/` | `play.views.report` | `play/report.html` |
| `/admin/` | Django Admin | темы со словами, слова, наборы, факты, профили |

Игры перечислены в `play/games.py` (`GAMES`): `choose`, `odd`, `sort`, `memory`, `assemble`,
`truefalse` и режим `hard`. Поле `by_topic=False` (у `odd`, `sort`, `hard`) убирает кнопки выбора темы.

## Служебные адреса

| Метод, путь | Ответ |
|---|---|
| `GET /content.json` | весь словарь: `{topics, words, sorting, facts, version}` (`vocab/content.py`); `version` — первые 12 символов sha256 от содержимого |
| `GET /media/<path>` | файл из хранилища с типом из `play/mime.py`; путь с `..` или несуществующий — 404 |
| `GET /bundle/manifest.json` | манифест офлайн-снимка, `Cache-Control: no-cache` |
| `GET /bundle/blobs/<sha256>` | блоб снимка, `Cache-Control: public, max-age=31536000, immutable`; другие имена — 404 |

Слово в `/content.json`: обязательные `id`, `topic` (slug), `udm`, `ru` и только заполненные из
`alt`, `tr` (транскрипция), `emoji`, `color`, `number`, `img`, `audio`.

## JSON API аккаунта (`play/api.py`)

Без cookies и CSRF. Авторизация — `Authorization: Bearer <token>`, токен — `signing.dumps(user.pk,
salt="votes.api")` без срока действия. Ошибки — `{"error": "текст для ребёнка"}` с кодом ответа.

| Метод, путь | Тело запроса | Успех | Ошибки |
|---|---|---|---|
| `POST /api/signup` | `{username, password, name, avatar, updated}` | `201 {token, username, save}` | 400 — пустое имя для входа или с пробелами, длиннее 150, пароль короче 6, имя занято (без учёта регистра), битый JSON; 429 |
| `POST /api/login` | `{username, password}` | `200 {token, username, save}` | 401 — неверное имя или пароль; 429 |
| `GET /api/save` | — | `200 {save}` | 401 — нет или неверный токен |
| `PUT /api/save` | `{save}` | `200 {save}` (очищенное) | 400 — неверная структура; 401; 409 `{save: серверное}` — присланное старее хранимого; 413 — тело больше 256 КБ |

Правила `PUT`:
- `clean_save` проверяет `v == 2`, целый неотрицательный `updated`, что `profile` — объект, а
  `words` / `days` / `games` — словари словарей. Имя обрезается до 60 символов, аватар — до 16
  (`clean_profile`, она же чистит имя и зверька при регистрации).
  `settings` — только булевы `sound` / `notifications` / `geo`, остальное заменяется значениями
  по умолчанию (`SETTINGS_DEFAULTS`).
- Сравнение `updated` идёт под `select_for_update`: равный `updated` принимается (повтор
  отправки), меньший — 409.
- Сохранения без блока `settings` (записаны до его появления) отдаются с настройками по умолчанию.

Ограничение частоты (`rate_limit`, счётчики в кэше Django, у каждого воркера gunicorn свои):

| Что | Лимит |
|---|---|
| попытки входа с одного IP | 60 в минуту |
| неверные пароли к одному имени (без учёта регистра) | 10 за 5 минут |
| регистрации с одного IP | 40 за 10 минут |

Превышение — `429` с `Retry-After: 60`. IP — последний адрес из `X-Forwarded-For` (его добавляет
Caddy), без заголовка — `REMOTE_ADDR`.

## Management-команды

| Команда | Что делает |
|---|---|
| `migrate` | стандартные миграции Django |
| `seed [--file путь] [--update]` | загружает `seeds/vocab.yaml`: темы по `slug` (`update_or_create`), слова по (тема, `udm`) — id не меняются. Без `--update` существующие слова не перезаписываются; докладываются только картинка и звук, которых нет (или копия из `seeds/media/` устарела по размеру), и пустые `alt`, `transcription`, `emoji`, `color`. Наборы сортировки — по `title`. Факты перезаливаются целиком с `--update` или если их ещё нет; факт не строкой — ошибка. Всё в одной транзакции |
| `build_bundle [--out папка]` | собирает офлайн-снимок в `BUNDLE_DIR` (по умолчанию `backend/bundle`): страницы из `page_urls()` через тестовый клиент, статика (в проде — файлы с хэшем из `staticfiles.json`, без `admin/`, `css/input.css`, `.gz`, `.br`), картинки и аудио слов. Пишет `blobs/<sha256>`, удаляет неиспользуемые блобы, последним атомарно пишет `manifest.json` |
| `createsuperuser --noinput` | в `entrypoint.sh`, если задан `DJANGO_SUPERUSER_USERNAME` |

`backend/entrypoint.sh` при каждом старте контейнера: `migrate --noinput` → `seed` → `build_bundle`
→ `createsuperuser` → `gunicorn` (3 воркера).

## Настройки окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DJANGO_DEBUG` | `1` | при `0` обязателен `DJANGO_SECRET_KEY`, статика — `CompressedManifestStaticFilesStorage` |
| `DJANGO_SECRET_KEY` | ключ для разработки (только с DEBUG) | подпись токенов входа |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | `*`, пусто | |
| `DJANGO_HTTPS_ONLY`, `DJANGO_HSTS_SECONDS` | `0`, год | Secure-cookie и HSTS |
| `DATABASE_URL` | SQLite `backend/db.sqlite3` | |
| `USE_S3`, `S3_*` | выключено | MinIO: `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_PUBLIC_DOMAIN`, `S3_PUBLIC_PROTOCOL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| `BUNDLE_DIR` | `backend/bundle` | куда пишет `build_bundle` и откуда отдаёт `/bundle/` |

`.env` читается из корня репозитория. Часовой пояс — `Europe/Samara` (Ижевск, UTC+4).

## Запуск

```bash
cd backend
mise install && mise run setup   # uv sync, migrate, seed
mise run dev                     # http://localhost:8000
mise run lint                    # ruff check, ruff format --check, makemigrations --check
mise run bundle                  # снимок в ../mobile/assets/bundle
```
