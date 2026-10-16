import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:votes/bundle.dart';

final server = Uri.parse('https://hakaton.marshmeg.ru');

String sha(List<int> data) => sha256.convert(data).toString();

/// Манифест в формате build_bundle: {"/путь": содержимое}.
String manifestJson(String version, int built, Map<String, String> files) => jsonEncode({
      'version': version,
      'built': built,
      'files': {
        for (final e in files.entries)
          e.key: {
            'sha': sha(utf8.encode(e.value)),
            'type': 'text/html; charset=utf-8',
            'size': e.value.length,
          },
      },
    });

/// Сервер снимка: отдаёт [manifest] и блобы [files]; [requests] — какие пути запрашивались.
MockClient fakeServer(
  String manifest,
  Map<String, String> files,
  List<String> requests, {
  int status = 200,
}) {
  final blobs = {for (final body in files.values) sha(utf8.encode(body)): body};
  return MockClient((request) async {
    final path = request.url.path;
    requests.add(path);
    if (status != 200) return http.Response('', status);
    if (path == '/bundle/manifest.json') return http.Response.bytes(utf8.encode(manifest), 200);
    final blob = blobs[path.replaceFirst('/bundle/blobs/', '')];
    return blob == null ? http.Response('', 404) : http.Response.bytes(utf8.encode(blob), 200);
  });
}

void main() {
  late Directory dir;
  late Bundle bundle;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('bundle_test');
    Directory('${dir.path}/blobs').createSync();
    bundle = Bundle.forTest(
      Manifest.parse(manifestJson('v1', 10, {'/': 'старая главная'})),
      dir,
    );
  });

  tearDown(() => dir.deleteSync(recursive: true));

  test('путь без слэша находит страницу со слэшем', () {
    final b = Bundle.forTest(
      Manifest.parse(manifestJson('v', 1, {'/learn/': 'темы'})),
      dir,
    );
    expect(b.lookup('/learn/'), isNotNull);
    expect(b.lookup('/learn'), isNotNull);
    expect(b.lookup('/nope'), isNull);
  });

  test('блоб читается с диска, отсутствующий — null', () async {
    final data = utf8.encode('привет');
    File('${dir.path}/blobs/${sha(data)}').writeAsBytesSync(data);
    expect(utf8.decode((await bundle.read(sha(data)))!), 'привет');
    expect(await bundle.read('0' * 64), isNull);
  });

  test('новая версия скачивается и сразу включается', () async {
    final files = {'/': 'новая главная', '/learn/': 'темы'};
    final requests = <String>[];
    final version = await bundle.update(
      server,
      httpClient: fakeServer(manifestJson('v2', 20, files), files, requests),
    );
    expect(version, 'v2');
    expect(bundle.version, 'v2');
    expect(bundle.pendingVersion, isNull);
    expect(
      utf8.decode((await bundle.read(bundle.lookup('/learn/')!.sha))!),
      'темы',
    );
    expect(File('${dir.path}/manifest.json').existsSync(), isTrue);
    // Временных файлов после загрузки не остаётся.
    expect(
      dir.listSync(recursive: true).where((f) => f.path.endsWith('.tmp')),
      isEmpty,
    );
  });

  test('уже скачанные блобы повторно не качаются', () async {
    final files = {'/': 'новая главная', '/learn/': 'темы'};
    final have = utf8.encode('темы');
    File('${dir.path}/blobs/${sha(have)}').writeAsBytesSync(have);
    final requests = <String>[];
    await bundle.update(
      server,
      httpClient: fakeServer(manifestJson('v2', 20, files), files, requests),
    );
    expect(requests, [
      '/bundle/manifest.json',
      '/bundle/blobs/${sha(utf8.encode('новая главная'))}',
    ]);
  });

  test('после freeze новая версия ждёт следующего запуска', () async {
    final files = {'/': 'новая главная'};
    bundle.freeze();
    final version = await bundle.update(
      server,
      httpClient: fakeServer(manifestJson('v2', 20, files), files, []),
    );
    expect(version, 'v2');
    expect(bundle.version, 'v1');
    expect(bundle.pendingVersion, 'v2');
    expect(File('${dir.path}/manifest.json').existsSync(), isTrue);
  });

  test('та же или более старая версия не качается', () async {
    final requests = <String>[];
    final files = {'/': 'другая главная'};
    expect(
      await bundle.update(
        server,
        httpClient: fakeServer(manifestJson('v1', 20, files), files, requests),
      ),
      isNull,
    );
    expect(
      await bundle.update(
        server,
        httpClient: fakeServer(manifestJson('v0', 5, files), files, requests),
      ),
      isNull,
    );
    expect(requests, everyElement('/bundle/manifest.json'));
    expect(bundle.version, 'v1');
  });

  test('блоб с неверным хэшем отменяет обновление', () async {
    final manifest = manifestJson('v2', 20, {'/': 'новая главная'});
    final client = MockClient(
      (request) async => request.url.path == '/bundle/manifest.json'
          ? http.Response.bytes(utf8.encode(manifest), 200)
          : http.Response.bytes(utf8.encode('подмена'), 200),
    );
    expect(await bundle.update(server, httpClient: client), isNull);
    expect(bundle.version, 'v1');
    expect(File('${dir.path}/manifest.json').existsSync(), isFalse);
    expect(Directory('${dir.path}/blobs').listSync(), isEmpty);
  });

  test('ошибка сервера или нет сети — обновления нет', () async {
    final files = {'/': 'новая главная'};
    expect(
      await bundle.update(
        server,
        httpClient: fakeServer('', files, [], status: 503),
      ),
      isNull,
    );
    final offline = MockClient(
      (_) async => throw const SocketException('нет сети'),
    );
    expect(await bundle.update(server, httpClient: offline), isNull);
    expect(bundle.version, 'v1');
  });
}
