import 'package:flutter_test/flutter_test.dart';
import 'package:votes/main.dart';

void main() {
  final server = Uri.parse('https://hakaton.marshmeg.ru');

  group('какие запросы WebView отдаются из снимка', () {
    test('GET страниц и статики нашего сервера — из снимка', () {
      expect(servedFromBundle(server.resolve('/'), 'GET', server), isTrue);
      expect(
        servedFromBundle(server.resolve('/learn/colors/'), null, server),
        isTrue,
      );
      expect(
        servedFromBundle(server.resolve('/static/js/app.js'), 'get', server),
        isTrue,
      );
    });

    test('API, админка и сам снимок — всегда из сети', () {
      for (final path in ['/api/save', '/admin/', '/bundle/manifest.json']) {
        expect(
          servedFromBundle(server.resolve(path), 'GET', server),
          isFalse,
          reason: path,
        );
      }
    });

    test('не GET — из сети', () {
      expect(servedFromBundle(server.resolve('/'), 'POST', server), isFalse);
      expect(servedFromBundle(server.resolve('/'), 'PUT', server), isFalse);
    });

    test('чужие адреса и другая схема или порт — из сети', () {
      expect(
        servedFromBundle(Uri.parse('https://example.com/'), 'GET', server),
        isFalse,
      );
      expect(
        servedFromBundle(
          Uri.parse('http://hakaton.marshmeg.ru/'),
          'GET',
          server,
        ),
        isFalse,
      );
      expect(
        servedFromBundle(
          Uri.parse('https://hakaton.marshmeg.ru:8443/'),
          'GET',
          server,
        ),
        isFalse,
      );
    });
  });

  group('тип файла из манифеста', () {
    test('MIME-тип и кодировка разделяются', () {
      final t = splitContentType('text/html; charset=utf-8');
      expect(t.mime, 'text/html');
      expect(t.charset, 'utf-8');
    });

    test('без кодировки — только MIME-тип', () {
      final t = splitContentType('image/png');
      expect(t.mime, 'image/png');
      expect(t.charset, isNull);
    });
  });
}
