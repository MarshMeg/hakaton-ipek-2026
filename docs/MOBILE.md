# Android-приложение (Flutter)

`mobile/` — обёртка над веб-приложением: InAppWebView открывает `https://hakaton.marshmeg.ru/`, а
страницы, статику, словарь и картинки отдаёт из офлайн-снимка на телефоне. Игровой логики в Dart
нет. Общая схема — в [ARCHITECTURE.md](ARCHITECTURE.md), установка инструментов — в
[local-setup.md](local-setup.md).

- Пакет Dart `votes`, application id и namespace Android — `ru.marshmeg.hakaton`.
- Android 8.0+ (`minSdk 26` в `android/app/build.gradle.kts`), Java 17, Flutter 3.47 (`mobile/mise.toml`).
- Зависимости (`pubspec.yaml`): `flutter_inappwebview` 6.2.0-beta.3, `path_provider`, `crypto`,
  `http`, `flutter_local_notifications`; для иконки — `flutter_launcher_icons`.

## Файлы

| Файл | Что делает |
|---|---|
| `lib/main.dart` | `VotesApp` → `GameScreen`: заставка, обновление снимка, InAppWebView, перехват запросов, кнопка «назад», экран ошибки |
| `lib/bundle.dart` | `Manifest`, `BundleFile`, `Bundle`: выбор активного снимка, чтение блобов, загрузка обновления, уборка старых блобов |
| `lib/bridge.dart` | `Bridge`: обработчики JS (`backup`, `restore`, `info`, `setNotifications`) |
| `android/app/src/main/AndroidManifest.xml` | разрешения и приёмники уведомлений |
| `android/app/build.gradle.kts` | `minSdk 26`, desugaring для `flutter_local_notifications`, release подписан debug-ключом |

Остальное в `android/` генерирует `flutter create` (`mise run setup`) и в git не хранится.

## Запуск приложения

1. `Bundle.load()`: читает манифест из assets APK (`assets/bundle/manifest.json`) и скачанный
   (`<app support>/bundle/manifest.json`), активным делает тот, у которого больше `built`. Удаляет
   скачанные блобы, на которые не ссылается ни один из манифестов.
2. Заставка «Проверяем обновления…»: `bundle.update(server)` не дольше `updateBudget` (20 с).
3. `bundle.freeze()` — дальше снимок до следующего запуска не меняется.
4. InAppWebView на `SERVER_URL/`. Вход и синхронизация сохранения — уже в JS (`app.js`).

### Обновление снимка (`Bundle.update`)

- `GET /bundle/manifest.json` с тайм-аутом 5 с; не 200, ошибка или нет сети — обновления нет.
- `Manifest.isUpdate`: новая версия должна быть непустой, с другой `version` и большим `built`.
- Качаются только блобы, которых нет ни на диске, ни в assets APK (тайм-аут 30 с на блоб).
  Каждый проверяется по sha256 — несовпадение отменяет всё обновление. Запись через `.tmp` + `rename`.
- Манифест пишется последним и атомарно. Если снимок ещё не заморожен — новая версия включается
  сразу, иначе запоминается в `pendingVersion` и включится при следующем запуске.

APK из CI идёт без снимка: при первом запуске (с интернетом) он скачивается целиком тем же
`update()`. Локально снимок можно положить в APK: `cd backend && mise run bundle` пишет его в
`mobile/assets/bundle/` (в git там только `.gitkeep`).

### Перехват запросов (`servedFromBundle`, `_intercept`)

Из снимка отдаются только `GET` к origin сервера, кроме путей `/api/`, `/admin/`, `/bundle/`.
Путь ищется в манифесте как есть, а без `/` на конце — ещё и со `/` (`/learn` → `/learn/`). Если
файла нет — запрос уходит в сеть. Ответ — `200` с типом и кодировкой из манифеста
(`splitContentType`) и `Cache-Control: no-store`, чтобы WebView не отдал из кэша старую версию
страницы после обновления. Адрес в WebView остаётся настоящим, поэтому localStorage и `/api/`
работают одинаково онлайн и офлайн.

Настройки WebView: `useShouldInterceptRequest`, JavaScript и DOM Storage включены, звук без жеста
пользователя, без зума; к User-Agent дописывается `VotesApp` — по нему `app.js` понимает, что открыт
в приложении, и ждёт мост.

Ошибка загрузки главного фрейма показывает экран «Страница не открылась» с кнопкой «Повторить»
(ошибки картинок и `/api/` игнорируются). Системная «назад» листает историю WebView.

## Мост для JS (`bridge.dart`)

JS вызывает `window.flutter_inappwebview.callHandler(имя, …)` через `ZB.Bridge.call`. Исключение в
обработчике пишется в лог, JS получает `null`.

| Обработчик | Аргументы | Результат |
|---|---|---|
| `backup` | строка JSON `{save, auth}` | `true`; пишет `save.json` в папку приложения (через `.tmp`, записи идут по очереди) |
| `restore` | — | содержимое `save.json`, а если его нет — старого `progress.json`; иначе `null` |
| `info` | — | `{bundle: версия снимка, pending: скачанная версия или null}` (экран «Настройки») |
| `setNotifications` | `bool` | включить — запросить разрешение и раз в день показывать «Слово дня ждёт тебя!» (`periodicallyShow`, `RepeatInterval.daily`, канал `daily_word`); `false`, если разрешения нет. Выключить — отменить |

Копия `save.json` нужна на случай очистки данных WebView: при запуске `app.js` берёт её, если она
новее localStorage.

## Разрешения (`AndroidManifest.xml`)

| Разрешение | Зачем |
|---|---|
| `INTERNET` | синхронизация сохранения и обновление снимка |
| `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED` | ежедневное напоминание и его восстановление после перезагрузки (приёмники `flutter_local_notifications`) |

Уведомления включаются только переключателем в «Настройках». В `<application>`
включён `usesCleartextTraffic="true"` (разрешены запросы по HTTP).

## Сборка

```bash
cd mobile
mise trust && mise install
mise run setup    # flutter create --platforms=android --org ru.marshmeg --project-name hakaton . + pub get + иконка
mise run check    # flutter analyze
mise run dev      # эмулятор, SERVER_URL=http://10.0.2.2:8000
mise run apk      # release APK для android-arm и android-arm64
```

Адрес сервера вшивается при сборке: `--dart-define=SERVER_URL=…`, по умолчанию
`https://hakaton.marshmeg.ru` (`defaultServerUrl` в `main.dart`).

CI (`.github/workflows/android.yml`) запускается при изменениях в `mobile/**` или в самом workflow
и вручную: `flutter create`, `pub get`, `flutter_launcher_icons`, `flutter analyze`,
`flutter build apk --release --target-platform android-arm,android-arm64
--dart-define=SERVER_URL=${vars.SERVER_URL || https://hakaton.marshmeg.ru}`. На `main` задача `release`
публикует GitHub Release `apk-<run_number>` с `votes.apk`; постоянная ссылка —
`https://github.com/MarshMeg/hakaton-ipek-2026/releases/latest/download/votes.apk`.
