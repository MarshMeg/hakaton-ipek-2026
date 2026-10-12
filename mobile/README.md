# Вотэс — Android-приложение

Flutter-обёртка: открывает веб-приложение (Django) во WebView. Платформенные файлы Android
генерируются командой `flutter create`, в репозитории хранится только `AndroidManifest.xml`
(разрешение на интернет и HTTP для локального сервера).

```bash
cd mobile
flutter create --platforms=android --org ru.votes .   # один раз, создаст android/
flutter pub get
flutter run                                            # сервер по умолчанию: https://hakaton.marshmeg.ru
flutter run --dart-define=SERVER_URL=http://10.0.2.2:8000   # локальный сервер из эмулятора
flutter build apk
```

Адрес сервера можно поменять прямо в приложении: на экране «Нет связи с сервером» →
«Изменить адрес сервера» (например, `http://192.168.0.10:8000` для телефона в той же Wi-Fi сети).
