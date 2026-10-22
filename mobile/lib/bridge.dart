// Мост между JS (static/js/app.js, объект ZB.Bridge) и телефоном. JS вызывает
// `window.flutter_inappwebview.callHandler(имя, ...)` и получает результат как Promise.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:path_provider/path_provider.dart';

import 'bundle.dart';

const _reminderId = 1;

/// Ежедневное напоминание: канал уведомлений Android и текст.
const _reminderDetails = NotificationDetails(
  android: AndroidNotificationDetails(
    'daily_word',
    'Слово дня',
    channelDescription: 'Ежедневное напоминание позаниматься',
  ),
);

class Bridge {
  Bridge(this.bundle);

  final Bundle bundle;
  final _notifications = FlutterLocalNotificationsPlugin();
  bool _notificationsReady = false;

  /// Регистрирует обработчики в WebView. Ошибка в обработчике не роняет приложение:
  /// она пишется в лог, а JS получает null.
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
  }

  // --- резервная копия прогресса ---
  // localStorage WebView может быть очищен; копия в файле приложения позволяет его восстановить.
  // JS передаёт строку {save, auth} (static/js/app.js) — здесь она хранится как есть.
  // Старые версии хранили журнал событий в progress.json: его отдаём, пока нет save.json,
  // чтобы JS перевёл его в сохранение.

  // Хвост очереди записей: каждая новая запись ждёт предыдущую (см. _backup), а _restore
  // ждёт все, чтобы не прочитать файл посреди записи.
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
    await _initNotifications();
    if (!enabled) {
      await _notifications.cancel(id: _reminderId);
      return true;
    }
    if (!await _requestNotificationsPermission()) return false;
    await _notifications.periodicallyShow(
      id: _reminderId,
      title: 'Слово дня ждёт тебя! ☀️',
      body: 'Загляни в «Ӟеч-а бур-а удмурт кыл?» и узнай новое удмуртское слово.',
      repeatInterval: RepeatInterval.daily,
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      notificationDetails: _reminderDetails,
    );
    return true;
  }

  // Плагин уведомлений настраивается один раз, при первом вызове.
  Future<void> _initNotifications() async {
    if (_notificationsReady) return;
    await _notifications.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      ),
    );
    _notificationsReady = true;
  }

  // На Android 13+ спрашивает разрешение, на старых версиях оно есть сразу.
  Future<bool> _requestNotificationsPermission() async {
    final android = _notifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    return await android?.requestNotificationsPermission() ?? true;
  }
}
