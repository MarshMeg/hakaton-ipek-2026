// Офлайн-снимок веб-приложения: страницы, статика, словарь и картинки.
//
// Снимок собирает бэкенд (`manage.py build_bundle`) в формате
//   manifest.json  {"version", "built", "files": {"/learn/": {"sha", "type", "size"}}}
//   blobs/<sha256> содержимое файлов (имя = хэш, поэтому файлы не дублируются).
// Первая версия скачивается при первом запуске (APK из CI идёт без снимка) или лежит в assets
// APK, если её туда положили при локальной сборке. При каждом запуске, до показа WebView, приложение проверяет обновление
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

/// Сколько ждать манифест с сервера (без сети — сразу работаем на текущем снимке).
const _manifestTimeout = Duration(seconds: 5);

/// Сколько ждать один блоб.
const _blobTimeout = Duration(seconds: 30);

/// Запись из manifest.json: хэш содержимого (имя блоба) и Content-Type.
class BundleFile {
  const BundleFile(this.sha, this.type);

  final String sha;
  final String type;
}

/// manifest.json снимка: версия, время сборки (мс) и файлы по пути запроса.
class Manifest {
  Manifest(this.version, this.built, this.files);

  final String version;
  final int built;
  final Map<String, BundleFile> files;

  // Пустой манифест — когда снимка нет ни в APK, ни на диске (built = 0, проиграет любому).
  static final empty = Manifest('', 0, const {});

  /// Хэши всех файлов (имена блобов) без повторов.
  Set<String> get shas => files.values.map((f) => f.sha).toSet();

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
  // Папка скачанного снимка: manifest.json и blobs/.
  final Directory _dir;
  // Блобы, которые уже есть в assets APK: их не качаем и читаем прямо из APK, поэтому
  // скачанная версия хранит на диске только то, чем отличается от встроенной.
  final Set<String> _assetShas;
  bool _frozen = false;

  /// Скачанная, но ещё не включённая версия (включится при следующем запуске).
  String? pendingVersion;

  String get version => manifest.version;
  bool get isEmpty => manifest.files.isEmpty;

  File get _manifestFile => File('${_dir.path}/manifest.json');
  File _blobFile(String sha) => File('${_dir.path}/blobs/$sha');

  /// Выбирает активную версию: скачанную или из APK — ту, что собрана позже
  /// (после установки нового APK его снимок может оказаться свежее скачанного).
  static Future<Bundle> load() async {
    final support = await getApplicationSupportDirectory();
    final dir = Directory('${support.path}/bundle');
    await Directory('${dir.path}/blobs').create(recursive: true);

    final fromAssets = await _assetManifest();
    final downloaded = await _downloadedManifest(File('${dir.path}/manifest.json'));
    final active = downloaded.built > fromAssets.built ? downloaded : fromAssets;
    final bundle = Bundle._(active, dir, fromAssets.shas);
    await bundle._collectGarbage();
    return bundle;
  }

  // Манифест снимка из assets APK; нет снимка — пустой.
  static Future<Manifest> _assetManifest() async {
    try {
      return Manifest.parse(await rootBundle.loadString('$_assetRoot/manifest.json'));
    } catch (e) {
      debugPrint('В APK нет офлайн-снимка: $e');
      return Manifest.empty;
    }
  }

  // Манифест скачанного снимка; файла нет или он повреждён — пустой.
  static Future<Manifest> _downloadedManifest(File file) async {
    if (!await file.exists()) return Manifest.empty;
    try {
      return Manifest.parse(await file.readAsString());
    } catch (e) {
      debugPrint('Повреждённый manifest.json, игнорирую: $e');
      return Manifest.empty;
    }
  }

  /// Файл снимка для пути запроса (`/learn` и `/learn/` — одна страница).
  BundleFile? lookup(String path) {
    return manifest.files[path] ?? (path.endsWith('/') ? null : manifest.files['$path/']);
  }

  /// Содержимое блоба: сначала скачанный файл на диске, потом assets APK. null — нет нигде.
  Future<Uint8List?> read(String sha) async {
    final file = _blobFile(sha);
    if (await file.exists()) return file.readAsBytes();
    if (_assetShas.contains(sha)) {
      final data = await rootBundle.load('$_assetRoot/blobs/$sha');
      return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
    }
    return null;
  }

  Future<bool> _hasBlob(String sha) async =>
      _assetShas.contains(sha) || await _blobFile(sha).exists();

  /// Дальше снимок не меняется до следующего запуска: WebView уже показывает страницы.
  void freeze() => _frozen = true;

  /// Скачивает новую версию снимка, если она есть, и включает её (если снимок ещё не
  /// заморожен). Возвращает её версию или null. Без сети за [manifestTimeout] — null.
  Future<String?> update(Uri server, {Duration manifestTimeout = _manifestTimeout}) async {
    final client = http.Client();
    try {
      final res = await client.get(server.resolve('/bundle/manifest.json')).timeout(manifestTimeout);
      if (res.statusCode != 200) return null;
      final remote = Manifest.parse(utf8.decode(res.bodyBytes));
      if (!Manifest.isUpdate(manifest, remote)) return null;

      // Качаем только те блобы, которых ещё нет ни на диске, ни в APK.
      for (final sha in remote.shas) {
        if (await _hasBlob(sha)) continue;
        if (!await _downloadBlob(client, server, sha)) return null;
      }

      // Манифест — последним и атомарно: до этого момента активна прежняя версия.
      await _writeAtomically(_manifestFile, res.bodyBytes);
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

  /// Скачивает блоб и проверяет его sha256. false — не скачался или хэш не совпал.
  Future<bool> _downloadBlob(http.Client client, Uri server, String sha) async {
    final blob = await client.get(server.resolve('/bundle/blobs/$sha')).timeout(_blobTimeout);
    if (blob.statusCode != 200) return false;
    if (sha256.convert(blob.bodyBytes).toString() != sha) {
      debugPrint('Блоб $sha не совпал по хэшу — обновление отменено');
      return false;
    }
    await _writeAtomically(_blobFile(sha), blob.bodyBytes);
    return true;
  }

  /// Запись через .tmp и rename: оборванная запись не оставит «целый» файл с неполным
  /// содержимым.
  Future<void> _writeAtomically(File target, List<int> bytes) async {
    final tmp = File('${target.path}.tmp');
    await tmp.writeAsBytes(bytes, flush: true);
    await tmp.rename(target.path);
  }

  /// Удаляет скачанные блобы, на которые не ссылается ни активный, ни скачанный манифест.
  Future<void> _collectGarbage() async {
    final keep = manifest.shas;
    final file = _manifestFile;
    if (await file.exists()) {
      try {
        keep.addAll(Manifest.parse(await file.readAsString()).shas);
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
