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

  test('обновление снимка: только другая и более свежая непустая версия', () {
    Manifest m(String version, int built, {bool empty = false}) => Manifest(
      version,
      built,
      empty ? const {} : const {'/': BundleFile('00', 'text/html')},
    );
    final current = m('a', 10);
    expect(Manifest.isUpdate(current, m('b', 20)), isTrue);
    expect(Manifest.isUpdate(current, m('a', 20)), isFalse);
    expect(Manifest.isUpdate(current, m('b', 5)), isFalse);
    expect(Manifest.isUpdate(current, m('b', 20, empty: true)), isFalse);
  });
}
