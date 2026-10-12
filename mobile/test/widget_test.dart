import 'package:flutter_test/flutter_test.dart';
import 'package:votes/main.dart';

void main() {
  test('адрес сервера по умолчанию задан', () {
    expect(Uri.parse(defaultServerUrl).hasScheme, isTrue);
  });
}
