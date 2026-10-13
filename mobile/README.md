# Вотэс — Android-приложение

Flutter-обёртка: открывает веб-приложение (Django) во WebView. Платформенные файлы Android
генерируются командой `flutter create`, в репозитории хранится только `AndroidManifest.xml`
(разрешение на интернет и HTTP для локального сервера).

Flutter 3.47 и Java 17 ставятся через mise (`mobile/mise.toml`), Android SDK — через Android Studio.
Подробно: [LOCAL_SETUP.md](../LOCAL_SETUP.md).

```bash
cd mobile
mise trust && mise install
mise run setup    # flutter create (создаст android/) + pub get + иконка приложения
mise run check    # flutter analyze + flutter test
mise run dev      # эмулятор против локального сервера http://10.0.2.2:8000
mise run apk      # release APK, сервер https://hakaton.marshmeg.ru
mise run apk:ask  # release APK, который при запуске спрашивает адрес сервера
```

Сборка `apk:ask` (`--dart-define=ASK_SERVER_URL=true`, в релизах — `votes-ask.apk`) при каждом
запуске показывает экран «Адрес сервера»: туда вводится адрес, который нужно открыть (например,
`http://192.168.0.10:8000` для телефона в той же Wi-Fi сети); последний адрес запоминается.
У обеих сборок один идентификатор приложения, поэтому на устройстве они заменяют друг друга.

В обычной сборке тот же экран открывается с экрана «Нет связи с сервером» → «Изменить адрес сервера».

## Иконка приложения
Иконка лежит в `assets/icon/`: `icon.png` — обычная, `icon_foreground.png` — передний слой адаптивной
иконки Android (фон — красный `#c8102e`, задан в `pubspec.yaml`). Оба PNG получены из SVG рядом:
```bash
rsvg-convert -w 1024 -h 1024 assets/icon/icon.svg -o assets/icon/icon.png
rsvg-convert -w 1024 -h 1024 assets/icon/icon_foreground.svg -o assets/icon/icon_foreground.png
```
В проект Android её раскладывает `dart run flutter_launcher_icons` — он входит в `mise run setup` и в CI.
