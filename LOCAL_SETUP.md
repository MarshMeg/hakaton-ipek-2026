# Локальная настройка окружения (инструкция для Claude Code)

Этот файл — задание для Claude Code на компьютере разработчика: настроить окружение проекта
«Вотэс» и проверить, что всё работает. Общее описание проекта — в `CLAUDE.md` и `README.md`.

## Главное правило: всё через mise

- Инструменты (Python, Tailwind CLI, Flutter, Java) ставятся **только через [mise](https://mise.jdx.dev)**.
  Не ставь их через brew/apt/pyenv/nvm/sdkman и не используй системный Python.
- Команды проекта запускаются как задачи mise: `mise run <задача>`. Список: `mise tasks`.
- Python-зависимости ставятся в `backend/.venv`, который mise создаёт и активирует сам.
  Не создавай venv вручную и не вызывай глобальный `pip`.
- Конфиги раздельные, каждая часть ставит только своё:

| Файл | Инструменты | Задачи |
|---|---|---|
| `mise.toml` (корень) | — | `up`, `down` (Docker) |
| `backend/mise.toml` | Python 3.12, Tailwind CLI 3.4.17 | `setup`, `dev`, `test`, `lint`, `fmt`, `css`, `css:watch`, `seed` |
| `mobile/mise.toml` | Flutter 3.47, Java temurin-17 | `setup`, `check`, `dev`, `apk` |

`backend/Dockerfile` тоже ставит Python через mise из `backend/mise.toml`, так что версии
локально и в контейнере совпадают.

## 1. Установить mise (один раз)

macOS / Linux:
```bash
curl https://mise.run | sh            # или: brew install mise
```
Подключить mise к shell (выбрать свою оболочку) и перезапустить терминал:
```bash
echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc     # zsh (macOS по умолчанию)
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc   # bash
```
Windows: использовать **WSL2** (Ubuntu) и дальше действовать как в Linux.

Проверка: `mise --version` и `mise doctor` — без ошибок.

> Если mise упирается в лимит GitHub API (ошибка `API rate limit exceeded` при установке
> Tailwind или Python), задай токен: `export GITHUB_TOKEN=<personal access token без прав>`.

## 2. Бэкенд (нужен всем)

```bash
cd backend
mise trust            # разрешить конфиг проекта (один раз)
mise install          # Python 3.12 + Tailwind CLI
mise run setup        # .venv, зависимости, миграции, стартовый курс
mise run test         # должно быть: 14 passed (или больше)
mise run lint         # ruff + проверка миграций, как в CI
mise run dev          # http://localhost:8000
```

Проверка: http://localhost:8000 открывает карту курса «Удмуртский для начинающих»,
урок проходится. Админка: http://localhost:8000/admin — суперпользователя создать командой
`mise exec -- python manage.py createsuperuser`.

Повседневные задачи (запускать из `backend/`):

| Задача | Что делает |
|---|---|
| `mise run test -- -k lesson` | один тест или группа (аргументы уходят в pytest) |
| `mise run fmt` | автоформатирование ruff |
| `mise run css` | пересобрать `static/css/app.css` после правки классов Tailwind в шаблонах |
| `mise run css:watch` | то же, в режиме наблюдения |
| `mise run seed` | перезагрузить курс из `seeds/content.yaml` |

`app.css` лежит в репозитории: после изменения классов в шаблонах обязательно `mise run css`
и закоммитить результат, иначе новые классы не будут работать.

## 3. Весь стек в Docker (по желанию)

Нужен установленный Docker (он не ставится через mise).
```bash
mise run up           # из корня репозитория: web + PostgreSQL + MinIO
mise run down
```
Сайт — http://localhost:8000 (админ `admin` / `admin12345`), консоль MinIO — http://localhost:9001.

## 4. Android-приложение (только тем, кто работает с `mobile/`)

Flutter и Java ставит mise, а **Android SDK** — Android Studio (mise его не ставит):
1. Установить Android Studio, в SDK Manager поставить Android SDK, Command-line Tools и
   эмулятор (AVD).
2. Дальше:
```bash
cd mobile
mise trust
mise install                          # Flutter 3.47 + Java 17 (≈1–2 ГБ)
mise exec -- flutter doctor           # Android toolchain должен быть ✓
mise exec -- flutter doctor --android-licenses
mise run setup                        # flutter create (платформенные файлы) + pub get
mise run check                        # flutter analyze + flutter test, как в CI
```
3. Запуск в эмуляторе против локального сервера (в другом терминале `cd backend && mise run dev`):
```bash
mise run dev
```
4. Release APK (сервер `https://hakaton.marshmeg.ru`): `mise run apk`.

Важно: в `mobile/android/` в git хранится только `app/src/main/AndroidManifest.xml`,
остальное генерирует `mise run setup` — не коммить сгенерированные файлы.
Готовый APK также собирает CI: релизы на GitHub, ссылка в README.

## Если что-то не так

| Симптом | Что делать |
|---|---|
| `mise ERROR ... not trusted` | `mise trust` в этой папке |
| `No module named django` | запускать через `mise run …` / `mise exec -- …` из `backend/`; при сломанном venv удалить `backend/.venv` и повторить `mise run setup` |
| Нет команды `python`/`flutter` | mise не активирован в shell — шаг 1, перезапустить терминал |
| `API rate limit exceeded` | задать `GITHUB_TOKEN` (см. шаг 1) |
| `flutter doctor`: нет Android SDK | поставить SDK через Android Studio, затем `flutter config --android-sdk <путь>` |
| Эмулятор не видит сервер | сервер должен слушать `0.0.0.0:8000`, в эмуляторе адрес `http://10.0.2.2:8000` |

## Готово, когда
- [ ] `cd backend && mise run test && mise run lint` — зелёные;
- [ ] http://localhost:8000 открывается, урок проходится до экрана итогов;
- [ ] (для мобильщиков) `cd mobile && mise run check` — без ошибок, приложение запускается в эмуляторе.
