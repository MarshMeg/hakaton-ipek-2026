import 'package:flutter_test/flutter_test.dart';
import 'package:votes/main.dart';

void main() {
  test('адрес сервера по умолчанию задан', () {
    expect(Uri.parse(defaultServerUrl).hasScheme, isTrue);
  });

  test('адрес сервера нормализуется', () {
    expect(normalizeServerUrl(' 192.168.0.10:8000 '), 'http://192.168.0.10:8000');
    expect(normalizeServerUrl('https://hakaton.marshmeg.ru'), 'https://hakaton.marshmeg.ru');
    expect(normalizeServerUrl(''), isNull);
    expect(normalizeServerUrl('ftp://example.com'), isNull);
  });
}
