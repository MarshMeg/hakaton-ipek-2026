// Офлайн-снимок веб-приложения: страницы, статика, словарь и картинки.
//
// Снимок собирает бэкенд (`manage.py build_bundle`) в формате
//   manifest.json  {"version", "built", "files": {"/learn/": {"sha", "type", "size"}}}
//   blobs/<sha256> содержимое файлов (имя = хэш, поэтому файлы не дублируются).
// Первая версия лежит в assets APK, поэтому приложение работает сразу после установки
// без интернета. При каждом запуске, до показа WebView, приложение проверяет обновление
// (main.dart): скачивает с сервера все новые блобы (каждый проверяется по sha256), последним —
// манифест, и сразу включает новую версию. После старта WebView снимок «замораживается»
// (freeze): если обновление не успело, оно включится при следующем запуске, так что во время
// игры страницы не меняются. Прогресс игрока хранится отдельно (localStorage WebView + копия
// в save.json) и обновлением не затрагивается.

import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

const _assetRoot = 'assets/bundle';

class BundleFile {
  const BundleFile(this.sha, this.type);

  final String sha;
  final String type;
}

class Manifest {
  Manifest(this.version, this.built, this.files);

  final String version;
  final int built;
  final Map<String, BundleFile> files;

  static final empty = Manifest('', 0, const {});

  static Manifest parse(String raw) {
    final data = jsonDecode(raw) as Map<String, dynamic>;
    final files = <String, BundleFile>{};
    (data['files'] as Map<String, dynamic>).forEach((url, value) {
      final f = value as Map<String, dynamic>;
      files[url] = BundleFile(f['sha'] as String, f['type'] as String);
    });
    return Manifest(data['version'] as String, (data['built'] as num?)?.toInt() ?? 0, files);
  }

  /// Стоит ли переходить на [remote]: другая версия, не пустая и собрана позже текущей
  /// (то же правило, что при выборе между снимком из APK и скачанным в [Bundle.load]).
  static bool isUpdate(Manifest current, Manifest remote) =>
      remote.files.isNotEmpty && remote.version != current.version && remote.built > current.built;
}

class Bundle {
  Bundle._(this.manifest, this._dir, this._assetShas);

  Manifest manifest;
  final Directory _dir;
  final Set<String> _assetShas;
  bool _frozen = false;

  /// Скачанная, но ещё не включённая версия (включится при следующем запуске).
  String? pendingVersion;

  String get version => manifest.version;
  bool get isEmpty => manifest.files.isEmpty;

  /// Выбирает активную версию: скачанную или из APK — ту, что собрана позже
  /// (после установки нового APK его снимок может оказаться свежее скачанного).
  static Future<Bundle> load() async {
    final support = await getApplicationSupportDirectory();
    final dir = Directory('${support.path}/bundle');
    await Directory('${dir.path}/blobs').create(recursive: true);

    var fromAssets = Manifest.empty;
    try {
      fromAssets = Manifest.parse(await rootBundle.loadString('$_assetRoot/manifest.json'));
    } catch (e) {
      debugPrint('В APK нет офлайн-снимка: $e');
    }
    var downloaded = Manifest.empty;
    final file = File('${dir.path}/manifest.json');
    if (await file.exists()) {
      try {
        downloaded = Manifest.parse(await file.readAsString());
      } catch (e) {
        debugPrint('Повреждённый manifest.json, игнорирую: $e');
      }
    }
    final active = downloaded.built > fromAssets.built ? downloaded : fromAssets;
    final assetShas = fromAssets.files.values.map((f) => f.sha).toSet();
    final bundle = Bundle._(active, dir, assetShas);
    await bundle._collectGarbage();
    return bundle;
  }

  /// Файл снимка для пути запроса (`/learn` и `/learn/` — одна страница).
  BundleFile? lookup(String path) {
    return manifest.files[path] ?? (path.endsWith('/') ? null : manifest.files['$path/']);
  }

  Future<Uint8List?> read(String sha) async {
    final file = File('${_dir.path}/blobs/$sha');
    if (await file.exists()) return file.readAsBytes();
    if (_assetShas.contains(sha)) {
      final data = await rootBundle.load('$_assetRoot/blobs/$sha');
      return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
    }
    return null;
  }

  Future<bool> _hasBlob(String sha) async =>
      _assetShas.contains(sha) || await File('${_dir.path}/blobs/$sha').exists();

  /// Дальше снимок не меняется до следующего запуска: WebView уже показывает страницы.
  void freeze() => _frozen = true;

  /// Скачивает новую версию снимка, если она есть, и включает её (если снимок ещё не
  /// заморожен). Возвращает её версию или null. Без сети за [manifestTimeout] — null.
  Future<String?> update(
    Uri server, {
    Duration manifestTimeout = const Duration(seconds: 5),
  }) async {
    final client = http.Client();
    try {
      final res = await client.get(server.resolve('/bundle/manifest.json')).timeout(manifestTimeout);
      if (res.statusCode != 200) return null;
      final remote = Manifest.parse(utf8.decode(res.bodyBytes));
      if (!Manifest.isUpdate(manifest, remote)) return null;

      for (final sha in remote.files.values.map((f) => f.sha).toSet()) {
        if (await _hasBlob(sha)) continue;
        final blob = await client
            .get(server.resolve('/bundle/blobs/$sha'))
            .timeout(const Duration(seconds: 30));
        if (blob.statusCode != 200) return null;
        if (sha256.convert(blob.bodyBytes).toString() != sha) {
          debugPrint('Блоб $sha не совпал по хэшу — обновление отменено');
          return null;
        }
        final tmp = File('${_dir.path}/blobs/$sha.tmp');
        await tmp.writeAsBytes(blob.bodyBytes, flush: true);
        await tmp.rename('${_dir.path}/blobs/$sha');
      }

      // Манифест — последним и атомарно: до этого момента активна прежняя версия.
      final tmp = File('${_dir.path}/manifest.json.tmp');
      await tmp.writeAsBytes(res.bodyBytes, flush: true);
      await tmp.rename('${_dir.path}/manifest.json');
      if (_frozen) {
        pendingVersion = remote.version;
      } else {
        manifest = remote;
      }
      return remote.version;
    } catch (e) {
      debugPrint('Обновление снимка не удалось: $e');
      return null;
    } finally {
      client.close();
    }
  }

  /// Удаляет скачанные блобы, на которые не ссылается ни активный, ни скачанный манифест.
  Future<void> _collectGarbage() async {
    final keep = manifest.files.values.map((f) => f.sha).toSet();
    final file = File('${_dir.path}/manifest.json');
    if (await file.exists()) {
      try {
        keep.addAll(Manifest.parse(await file.readAsString()).files.values.map((f) => f.sha));
      } catch (_) {}
    }
    await for (final entity in Directory('${_dir.path}/blobs').list()) {
      final name = entity.uri.pathSegments.last;
      if (entity is File && !keep.contains(name)) {
        await entity.delete();
      }
    }
  }
}
