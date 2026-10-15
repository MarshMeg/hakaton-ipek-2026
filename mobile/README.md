# «Ӟеч-а бур-а удмурт кыл?» — Android-приложение

Flutter-обёртка над веб-приложением, которая работает **без интернета**:

- `lib/main.dart` — InAppWebView открывает `https://hakaton.marshmeg.ru/`, но каждый GET-запрос к
  этому адресу перехватывается и обслуживается из офлайн-снимка. В сеть уходят только `/api/`
  (облачный аккаунт), `/admin/` и `/bundle/`.
- `lib/bundle.dart` — офлайн-снимок: версия из `assets/bundle/` (кладётся в APK) или скачанная
  с сервера, выбирается более свежая. Обновление качается в фоне: только новые файлы, проверка
  sha256, манифест пишется последним. Включается при следующем запуске.
- `lib/bridge.dart` — функции телефона для JS: резервная копия прогресса в файле, уведомление
  «Слово дня», примерная геолокация, «Поделиться».

Снимок собирает бэкенд: `cd backend && mise run bundle` (в CI — автоматически перед сборкой APK).
В git хранятся только `lib/`, `test/`, `pubspec.yaml`, `AndroidManifest.xml` и `app/build.gradle.kts`
(minSdk 26 = Android 8.0). Остальные платформенные файлы генерирует `flutter create`.

Flutter 3.47 и Java 17 ставятся через mise (`mobile/mise.toml`), Android SDK — через Android Studio.
Подробно: [LOCAL_SETUP.md](../LOCAL_SETUP.md).

```bash
cd backend && mise run bundle && cd ../mobile
mise trust && mise install
mise run setup    # flutter create (создаст android/) + pub get + иконка приложения
mise run check    # flutter analyze + flutter test
mise run dev      # эмулятор против локального сервера http://10.0.2.2:8000
mise run apk      # release APK, сервер https://hakaton.marshmeg.ru
mise run apk:ask  # release APK, который при запуске спрашивает адрес сервера
```

Сборка `apk:ask` (`--dart-define=ASK_SERVER_URL=true`, в релизах — `votes-ask.apk`) при каждом
запуске показывает экран «Адрес сервера» (например, `http://192.168.0.10:8000` для телефона в той же
Wi-Fi сети); последний адрес запоминается, офлайн-снимок отдаётся по этому адресу. У обеих сборок
один идентификатор приложения, поэтому на устройстве они заменяют друг друга. В обычной сборке тот же
экран открывается с экрана ошибки → «Изменить адрес сервера».

## Иконка приложения
Иконка лежит в `assets/icon/`: `icon.png` — обычная, `icon_foreground.png` — передний слой адаптивной
иконки Android (фон — красный `#c8102e`, задан в `pubspec.yaml`). Оба PNG получены из SVG рядом:
```bash
rsvg-convert -w 1024 -h 1024 assets/icon/icon.svg -o assets/icon/icon.png
rsvg-convert -w 1024 -h 1024 assets/icon/icon_foreground.svg -o assets/icon/icon_foreground.png
```
В проект Android её раскладывает `dart run flutter_launcher_icons` — он входит в `mise run setup` и в CI.
