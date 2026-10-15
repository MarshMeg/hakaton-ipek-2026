import 'package:flutter_test/flutter_test.dart';
import 'package:votes/bundle.dart';
import 'package:votes/main.dart';

void main() {
  test('адрес сервера по умолчанию задан', () {
    expect(Uri.parse(defaultServerUrl).hasScheme, isTrue);
  });

  test('манифест офлайн-снимка читается', () {
    final m = Manifest.parse(
      '{"version": "abc", "built": 5, "files": {"/learn/": {"sha": "00", "type": "text/html", "size": 1}}}',
    );
    expect(m.version, 'abc');
    expect(m.built, 5);
    expect(m.files['/learn/']!.type, 'text/html');
  });
}
