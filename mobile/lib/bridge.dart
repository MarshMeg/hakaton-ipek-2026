// Мост между JS (static/js/app.js, объект ZB.Bridge) и телефоном. JS вызывает
// `window.flutter_inappwebview.callHandler(имя, ...)` и получает результат как Promise.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import 'bundle.dart';

const _reminderId = 1;

class Bridge {
  Bridge(this.bundle);

  final Bundle bundle;
  final _notifications = FlutterLocalNotificationsPlugin();
  bool _notificationsReady = false;

  void attach(InAppWebViewController controller) {
    void handle(String name, Future<Object?> Function(List<dynamic> args) fn) {
      controller.addJavaScriptHandler(
        handlerName: name,
        callback: (args) async {
          try {
            return await fn(args);
          } catch (e) {
            debugPrint('bridge $name: $e');
            return null;
          }
        },
      );
    }

    handle('backup', (args) => _backup(args.first as String));
    handle('restore', (_) => _restore());
    handle('info', (_) async => {'bundle': bundle.version, 'pending': bundle.pendingVersion});
    handle('setNotifications', (args) => _setNotifications(args.first == true));
    handle('location', (_) => _location());
    handle('share', (args) async {
      await SharePlus.instance.share(ShareParams(text: args.first as String));
      return true;
    });
  }

  // --- резервная копия прогресса ---
  // localStorage WebView может быть очищен; копия в файле приложения позволяет его восстановить.
  // JS передаёт строку {save, auth} (static/js/app.js) — здесь она хранится как есть.
  // Старые версии хранили журнал событий в progress.json: его отдаём, пока нет save.json,
  // чтобы JS перевёл его в сохранение.

  Future<void> _writing = Future.value();

  Future<File> _file(String name) async {
    final dir = await getApplicationSupportDirectory();
    return File('${dir.path}/$name');
  }

  Future<bool> _backup(String json) {
    jsonDecode(json); // не сохраняем мусор вместо прогресса
    // Записи идут по очереди: две копии подряд не должны писать в один .tmp одновременно.
    final done = _writing.then((_) async {
      final file = await _file('save.json');
      final tmp = File('${file.path}.tmp');
      await tmp.writeAsString(json, flush: true);
      await tmp.rename(file.path);
      return true;
    });
    _writing = done.catchError((_) => false);
    return done;
  }

  Future<String?> _restore() async {
    await _writing;
    for (final name in ['save.json', 'progress.json']) {
      final file = await _file(name);
      if (await file.exists()) return file.readAsString();
    }
    return null;
  }

  // --- уведомления: раз в день напоминание про «Слово дня» ---

  Future<bool> _setNotifications(bool enabled) async {
    if (!_notificationsReady) {
      await _notifications.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        ),
      );
      _notificationsReady = true;
    }
    final android = _notifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    if (!enabled) {
      await _notifications.cancel(id: _reminderId);
      return true;
    }
    final granted = await android?.requestNotificationsPermission() ?? true;
    if (!granted) return false;
    await _notifications.periodicallyShow(
      id: _reminderId,
      title: 'Слово дня ждёт тебя! ☀️',
      body: 'Загляни в «Ӟеч-а бур-а удмурт кыл?» и узнай новое удмуртское слово.',
      repeatInterval: RepeatInterval.daily,
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          'daily_word',
          'Слово дня',
          channelDescription: 'Ежедневное напоминание позаниматься',
        ),
      ),
    );
    return true;
  }

  // --- геолокация: только примерное место, для «сколько км до Ижевска» ---

  Future<Map<String, double>?> _location() async {
    if (!await Geolocator.isLocationServiceEnabled()) return null;
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
      return null;
    }
    final last = await Geolocator.getLastKnownPosition();
    final pos = last ??
        await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.low,
            timeLimit: Duration(seconds: 15),
          ),
        );
    return {'lat': pos.latitude, 'lon': pos.longitude};
  }
}
