# Вотэс — Android-приложение

Flutter-обёртка: открывает веб-приложение (Django) во WebView. Платформенные файлы Android
генерируются командой `flutter create`, в репозитории хранится только `AndroidManifest.xml`
(разрешение на интернет и HTTP для локального сервера).

Flutter 3.47 и Java 17 ставятся через mise (`mobile/mise.toml`), Android SDK — через Android Studio.
Подробно: [LOCAL_SETUP.md](../LOCAL_SETUP.md).

```bash
cd mobile
mise trust && mise install
mise run setup    # flutter create (создаст android/) + pub get
mise run check    # flutter analyze + flutter test
mise run dev      # эмулятор против локального сервера http://10.0.2.2:8000
mise run apk      # release APK, сервер https://hakaton.marshmeg.ru
```

Адрес сервера можно поменять прямо в приложении: на экране «Нет связи с сервером» →
«Изменить адрес сервера» (например, `http://192.168.0.10:8000` для телефона в той же Wi-Fi сети).
