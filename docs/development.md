# Заметки для разработчика

Как устроен код и как с ним работать. Схема компонентов — в [architecture.md](architecture.md),
настройка окружения с нуля — в [local-setup.md](local-setup.md).

## Проект

«Ӟеч-а бур-а удмурт кыл?» (команда «Вотэс») — приложение для детей 5–10 лет, которые учат удмуртский
язык. Сделано для хакатона «Удмуртский ИТ-класс „Вотэс“» (мобильный трек) по ТЗ заказчика: главное
меню Обучение / Игры / Профиль / Настройки, карточки слов по темам, шесть игр, статистика и отчёт,
**работа без интернета**, Android 8.0+. Весь текст интерфейса, комментарии, сообщения коммитов и
документация — **на русском**. Сроки и план — в `ROADMAP.md`.

Архитектура в одной фразе: Django рендерит **одинаковые для всех игроков страницы** (Alpine.js +
Tailwind); **логика игр и прогресс живут в JS на клиенте** (`backend/static/js/`);
`manage.py build_bundle` делает из сайта **офлайн-снимок**, который **Flutter-обёртка** (`mobile/`)
отдаёт WebView из assets APK, перехватывая запросы. В Dart нет игровой логики: он только отдаёт и
обновляет снимок и даёт JS доступ к возможностям телефона.

## Команды

Все инструменты — **через mise** (обязательно, см. [local-setup.md](local-setup.md)). Конфиги
раздельные, каждая часть ставит только своё: `backend/mise.toml` (uv и Tailwind CLI; uv ставит
Python 3.12 по `backend/.python-version` и зависимости в `backend/.venv`), `mobile/mise.toml`
(Flutter 3.47, Java 17), корневой `mise.toml` (только задачи Docker). Системный Python/pip не
используем; команды — `mise run <задача>` или `mise exec -- uv run <команда>` из нужной папки.
Зависимости — в `backend/pyproject.toml` + `backend/uv.lock` (меняются через `uv add`/`uv remove`,
коммитятся оба файла); `requirements*.txt` нет.

Бэкенд (из `backend/`):

```bash
mise install && mise run setup                          # uv sync, миграции, словарь (seed идемпотентен)
mise run dev                                            # runserver 0.0.0.0:8000
mise run test                                           # pytest (настройки в pyproject.toml)
mise run test -- tests/test_api.py::test_put_older_conflicts   # один тест
mise run lint                                           # ruff check + format --check + проверка миграций (как в CI)
mise run fmt | css | seed | bundle                      # формат / app.css / seed --update / снимок → mobile/assets/bundle
```

Без `DATABASE_URL` используется SQLite, без `USE_S3=1` медиа лежат в `backend/media/`.
`DJANGO_SECRET_KEY` обязателен при `DJANGO_DEBUG=0` (иначе настройки падают с
`ImproperlyConfigured`); с DEBUG (по умолчанию в `mise run dev` и тестах) берётся ключ для
разработки. `docker-compose.yml` передаёт локальный ключ по умолчанию, `docker-compose.prod.yml`
без ключа в `.env` не запускается; Dockerfile и `android.yml` подставляют фиктивный ключ только
для `collectstatic`/`build_bundle`.

Весь стек: `mise run up` (= `docker compose up --build`) из корня (сайт на :8000, консоль MinIO на
:9001, админ `admin`/`admin12345`). `backend/entrypoint.sh` при каждом старте выполняет `migrate`,
`seed`, `build_bundle` и `createsuperuser`. `backend/Dockerfile` — `python:3.12-slim` + бинарник uv:
`uv sync --locked --no-dev` и `/app/.venv/bin` в `PATH`, поэтому зависимости в образе и локально
одни и те же.

CSS: `backend/static/css/app.css` **собирается и коммитится**. После добавления классов Tailwind
пересоберите его через `mise run css` (standalone Tailwind CLI v3.4.17, без Node; сканирует
`backend/templates/` и `backend/static/js/`). Классов, которых нет в собранном CSS, просто не будет.

Мобильное приложение (`cd mobile && mise run setup | check | dev | apk`; Android SDK —
из Android Studio, не из mise; APK собирает CI): в git только `lib/`, `test/`, `pubspec.yaml`,
`assets/icon/`, `assets/bundle/**/.gitkeep`, `android/app/src/main/AndroidManifest.xml` и
`android/app/build.gradle.kts` (minSdk 26, desugaring для `flutter_local_notifications`) — остальное
в `android/` генерирует `flutter create --platforms=android --org ru.marshmeg --project-name hakaton .`
(`mise run setup`; существующие файлы он не перезаписывает). Application id и namespace Android —
`ru.marshmeg.hakaton` (пакет Dart по-прежнему `votes`); `--project-name hakaton` кладёт `MainActivity.kt`
в этот пакет. Старую папку `android/app/src/main/kotlin/ru/votes/` от прежней настройки можно удалить.
Снимок в `mobile/assets/bundle/` генерируется (`cd backend && mise run bundle`) и не коммитится.
Иконка — `mobile/assets/icon/*.png` (отрисованы из `.svg` рядом); `dart run flutter_launcher_icons`
(в `mise run setup` и в CI) записывает её поверх стандартной иконки Flutter.
`mobile/test/widget_test.dart` должен оставаться в репозитории: иначе `flutter create` сгенерирует
тест по умолчанию со ссылкой на `MyApp`, и `flutter analyze` упадёт.

## CI/CD (`.github/workflows/`)

`ci.yml` запускается на каждый push и PR. Задача `tests` (проверка `tests/ci`): ruff, проверка
миграций на PostgreSQL 16 (сервис-контейнер, `makemigrations --check` и `migrate`), pytest. На push в
`main` дальше идут `build` — образ web из `backend/` собирается в GitHub Actions (кэш слоёв `type=gha`)
и публикуется в GHCR как `ghcr.io/marshmeg/hakaton-ipek-2026/web:<sha>` и `:latest` — и `deploy`.

`android.yml` (push только в `main`, ветки — через `pull_request`) запускается при изменениях в
`mobile/**` или в самом workflow (и вручную через `workflow_dispatch`): `flutter analyze`,
`flutter test`, `flutter build apk`; на `main` задача `release` публикует GitHub Release
`apk-<run_number>` с `votes.apk`. Офлайн-снимок в CI не собирается: APK скачивает его с сервера
при первом запуске, поэтому правки бэкенда не пересобирают APK. Постоянная ссылка —
`releases/latest/download/votes.apk`; адрес сервера в APK — `vars.SERVER_URL || https://hakaton.marshmeg.ru`
(он же значение по умолчанию в `mobile/lib/main.dart`).

Деплой: задача `deploy` в `ci.yml` (push в `main`, после `build`) копирует compose-файлы и `deploy/`
rsync'ом в `/opt/votes` на сервер (`vars.DEPLOY_USER@vars.DEPLOY_HOST`, ключ в `secrets.DEPLOY_SSH_KEY`),
входит на сервере в GHCR временным `GITHUB_TOKEN` и запускает `deploy/deploy.sh <образ>`: тот
скачивает образ, ставит работающему образу тег `votes-web:previous`, новому — `votes-web:current`
(из него web запускается в `docker-compose.prod.yml`) и делает `up -d --no-build`. Затем задача
проверяет `vars.DEPLOY_URL/content.json`; если сайт не ответил — `deploy.sh --rollback` возвращает
`votes-web:previous`, и задача падает. Миграции БД откат не отменяет.
`docker-compose.prod.yml` добавляет Caddy (`deploy/Caddyfile`: HTTPS,
`/votes-media/*` → MinIO) и закрывает наружные порты web и MinIO. `/opt/votes/.env` на сервере не в git
и исключён из rsync. Прод включает `DJANGO_HTTPS_ONLY=1` (Secure-cookie и HSTS). Образ MinIO —
`pgsty/minio` (официальный `minio/minio` убрали из реестров). В продовой БД остались таблицы удалённых
приложений `courses`/`learning` (и представление `learning_player_xp`) — они не используются.
`accounts/0004` переносит `User.first_name` в `Profile.display_name` и удаляет старые игровые поля.

## Бэкенд

Три Django-приложения в `backend/`:

- `vocab` — контент: `Topic → Word` (+ `SortingSet` для «Сортировки», `Fact` для профиля), правится
  в админке или загружается из `seeds/vocab.yaml` командой `vocab/management/commands/seed.py`.
  Seed ищет темы по slug, а слова — по (тема, udm), поэтому **id слов не меняются**, а прогресс в
  сохранениях привязан именно к id. Без `--update` уже загруженные слова не меняются, только
  картинка или звук, появившиеся в файле позже, докладываются словам, у которых их ещё нет. `kind` темы (words/numbers/colors/phrases) определяет запасную
  «картинку» (эмодзи, цифра, цветной круг); `family` разводит близкие темы в «Найди лишнее».
  `content.py` строит `/content.json` — единый документ, который читают все игры. Здесь же страницы
  обучения (`/learn/`, `/learn/<slug>/` — карточки темы).
- `play` — страницы (`views.py`: главная, игры, игра, профиль, настройки, отчёт — одинаковые для всех,
  без CSRF-токенов и данных игрока в HTML, проверяется в `test_pages.py`), `/media/` из хранилища,
  `/bundle/` (раздаёт `BUNDLE_DIR`), JSON API аккаунта (`api.py`, подписанный Bearer-токен, без CSRF):
  `POST /api/signup`, `POST /api/login` → `{token, username, save}`; `GET|PUT /api/save` — PUT
  сохраняет, только если `save.updated >= stored.updated`, иначе `409 {save: серверное}`; лимит 256 КБ
  → 413; вход и регистрация ограничены по частоте через кэш Django (`rate_limit`: по IP — последнему
  адресу из `X-Forwarded-For`, который добавляет Caddy, и по неверным паролям к имени) → `429`.
  `management/commands/build_bundle.py` рендерит все страницы тестовым клиентом и вместе со статикой
  и медиа складывает в `manifest.json` + `blobs/<sha256>` (имя = хэш содержимого; версия зависит
  только от содержимого).
- `accounts` — `Profile.save_data`: **сохранение** аккаунта (один JSON-документ, формат v2:
  `{v, updated, profile: {name, avatar}, words: {id: {ok, bad, seen, streak, last}},
  days: {YYYY-MM-DD: {ok, bad, seen}}, games: {slug: {ok, bad, played, best}}}`), плюс скопированные
  из него `updated`/`display_name`/`avatar` для админки. Поле не названо `save`, чтобы не затенять
  `Model.save()`. Миграция `accounts/0005` свернула старый журнал `play.Attempt` в сохранения
  (`build_save`), `play/0002` удалила журнал.

## Клиент (`backend/static/js/`)

Обычный ES2017 (WebView Android 8), подключается до Alpine.

`app.js` — вход **обязателен** (гостевого режима нет; для первого входа нужна сеть). localStorage:
`zb.save.v2` (сохранение), `zb.auth.v1` (`{username, token, synced}`, в сохранение не входит),
`zb.settings.v1` (настройки устройства); старый журнал `zb.state.v1` при загрузке сворачивается
в сохранение (`fromEvents`). `ZB.Save.commit(mutator)` — единственный способ изменить прогресс;
вызывается на *конечных действиях* (игра пройдена, ушли со страницы карточек или нажали «Готово»,
изменён профиль): ставит `updated = now`, пишет в localStorage, отправляет копию `{save, auth}` во
Flutter через `ZB.Bridge` и делает `PUT`, не дожидаясь ответа (409 → берём серверное, 401 → окно
входа, нет сети → остаётся на телефоне). `boot()` проходит полный цикл один раз за запуск
(флаг `zb.booted` в sessionStorage): восстановление из копии во Flutter, затем `GET /api/save`
с тайм-аутом 5 с — более новое сохранение (по `updated`) целиком заменяет другое, без слияния.
`Alpine.store('app').phase` — `loading` (заставка) | `auth` (окно входа `templates/_auth.html`) |
`ready`. `computeStats(save, content)` считает опыт, серию дней, выученные слова, график и т. д.
из агрегатов сохранения.

`games.js` — шесть игр и `hard` («Трудные слова»: «Выбери перевод» по `ZB.hardWords(save)`, нужно
не меньше 3 таких слов) в виде компонентов `Alpine.data` на общей основе `base()`. Ответы копятся
в `this.answers` и записываются один раз в `finish()` (брошенная игра ничего не сохраняет).
Новая игра — это запись в `play/games.py`, компонент в `games.js` и шаблон
`templates/play/games/<slug>.html`.

## Мобильное приложение (`mobile/lib/`)

- `bundle.dart` — активный снимок: скачанный или из assets APK (в APK из CI его нет), тот, у которого `built` новее;
  `update()` докачивает недостающие блобы, проверяет sha256, пишет манифест последним и сразу
  переключается на новую версию, если ещё не было `freeze()`.
- `main.dart` — при каждом запуске: заставка «Проверяем обновления…», `await bundle.update()` не
  дольше 20 с (тайм-аут манифеста 5 с, без сети — пропуск), `freeze()`, затем InAppWebView с
  `shouldInterceptRequest`, который отдаёт GET-запросы к серверу из снимка; `/api/`, `/admin/`,
  `/bundle/` идут в сеть; в User-Agent добавляется `VotesApp`.
- `bridge.dart` — обработчики для JS: `backup`, `restore` (строка `{save, auth}` в `save.json`, при
  её отсутствии — старый `progress.json`), `info`, `setNotifications`, `location`, `share`.

## Оформление

Цвета и шрифты бренда — токены в `backend/tailwind.config.js` (продублированы в `mobile/lib/main.dart`).
Нейтральные и «мягкие» цвета (`surface`, `line`, `muted`, `ok-soft`, `brand-redSoft`, …) — CSS-переменные
в `backend/static/css/input.css` с тёмной темой через `prefers-color-scheme`; в шаблонах и JS используйте
их, а не `bg-white` / `gray-*` / `red-50`, иначе сломается тёмная тема. Шрифты и Alpine лежат
в `backend/static/` (никаких CDN: нужен офлайн, и шрифт должен содержать удмуртские буквы).

Медиа хранятся через `django-storages` в MinIO при `USE_S3=1`, но страницы и `/content.json` всегда
ссылаются на них как `/media/<имя>` (отдаёт `play.views.media`), поэтому одни и те же адреса работают
и онлайн, и внутри снимка.

## Контент

`seeds/vocab.yaml` взят из «Материалов к кейсу» заказчика (порядок приведён к «удм — рус»; известные
сомнения записаны в `needs_check`). До сдачи его, как и факты, должен проверить носитель языка
(«контент соответствует действительности» — критерий оценки). Не добавляйте удмуртские слова, фразы,
названия тем или похвалу на удмуртском без пометки, что они не проверены.
