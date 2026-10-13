// Вотэс — Android-приложение. Вся игра работает на сервере (Django) и открывается во WebView;
// приложение отвечает за запуск, экран «нет связи», кнопку «назад» и выбор адреса сервера.

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

/// Адрес по умолчанию задаётся при сборке: flutter build apk --dart-define=SERVER_URL=https://...
/// Для локального сервера в эмуляторе: --dart-define=SERVER_URL=http://10.0.2.2:8000
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://hakaton.marshmeg.ru');

/// Сборка «с выбором адреса»: --dart-define=ASK_SERVER_URL=true. При каждом запуске приложение
/// сначала спрашивает, какой адрес открыть (для проверки на локальном или тестовом сервере).
const bool askServerUrl = bool.fromEnvironment('ASK_SERVER_URL');

const String _prefsKey = 'server_url';

/// Приводит введённый адрес к виду со схемой; null — если это не http(s)-адрес.
/// Без схемы подставляется http:// — так обычно вводят локальный сервер (192.168.0.10:8000).
String? normalizeServerUrl(String input) {
  var text = input.trim();
  if (text.isEmpty) return null;
  if (!text.contains('://')) text = 'http://$text';
  final uri = Uri.tryParse(text);
  if (uri == null || uri.host.isEmpty) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  return uri.toString();
}

// Цвета брендбука (совпадают с backend/tailwind.config.js).
const Color brandRed = Color(0xFFC8102E);
const Color brandPaper = Color(0xFFFBF7F0);
const Color brandInk = Color(0xFF1B1B1B);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const VotesApp());
}

class VotesApp extends StatelessWidget {
  const VotesApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Вотэс',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: brandRed, surface: brandPaper),
        scaffoldBackgroundColor: brandPaper,
        useMaterial3: true,
      ),
      home: const GameScreen(),
    );
  }
}

class GameScreen extends StatefulWidget {
  const GameScreen({super.key});

  @override
  State<GameScreen> createState() => _GameScreenState();
}

class _GameScreenState extends State<GameScreen> {
  late final WebViewController _controller;
  String _serverUrl = defaultServerUrl;
  bool _loading = true;
  bool _offline = false;
  bool _asking = false;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(brandPaper)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) => setState(() => _loading = true),
          onPageFinished: (_) => setState(() => _loading = false),
          onWebResourceError: (error) {
            // Ошибки картинок/аудио не должны закрывать игру — реагируем только на саму страницу.
            if (error.isForMainFrame ?? true) {
              setState(() {
                _offline = true;
                _loading = false;
              });
            }
          },
        ),
      );
    // Android WebView сам не открывает выбор файла для <input type="file"> (аватарка в профиле):
    // показываем системную галерею и отдаём странице выбранную картинку.
    final platform = _controller.platform;
    if (platform is AndroidWebViewController) {
      platform.setOnShowFileSelector((_) async {
        final image = await ImagePicker().pickImage(source: ImageSource.gallery);
        return image == null ? [] : [Uri.file(image.path).toString()];
      });
    }
    _loadSavedUrl();
  }

  Future<void> _loadSavedUrl() async {
    final prefs = await SharedPreferences.getInstance();
    _serverUrl = prefs.getString(_prefsKey) ?? defaultServerUrl;
    if (!mounted) return;
    if (askServerUrl) {
      setState(() => _asking = true);
    } else {
      _open();
    }
  }

  void _open() {
    setState(() {
      _asking = false;
      _offline = false;
      _loading = true;
    });
    _controller.loadRequest(Uri.parse(_serverUrl));
  }

  Future<void> _applyServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, url);
    _serverUrl = url;
    _open();
  }

  @override
  Widget build(BuildContext context) {
    // Системная кнопка «назад» сначала листает историю WebView и только потом закрывает приложение.
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final navigator = Navigator.of(context);
        if (await _controller.canGoBack()) {
          await _controller.goBack();
        } else {
          navigator.maybePop();
        }
      },
      child: Scaffold(
        body: SafeArea(
          child: _asking
              ? _ServerUrlView(initialUrl: _serverUrl, onSubmit: _applyServerUrl)
              : _offline
              ? _OfflineView(
                  serverUrl: _serverUrl,
                  onRetry: _open,
                  onEditUrl: () => setState(() => _asking = true),
                )
              : Stack(
                  children: [
                    WebViewWidget(controller: _controller),
                    if (_loading)
                      const LinearProgressIndicator(color: brandRed, minHeight: 3),
                  ],
                ),
        ),
      ),
    );
  }
}

class _OfflineView extends StatelessWidget {
  const _OfflineView({
    required this.serverUrl,
    required this.onRetry,
    required this.onEditUrl,
  });

  final String serverUrl;
  final VoidCallback onRetry;
  final VoidCallback onEditUrl;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.wifi_off_rounded, size: 72, color: brandRed),
            const SizedBox(height: 16),
            const Text(
              'Нет связи с сервером',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: brandInk),
            ),
            const SizedBox(height: 8),
            Text(serverUrl, textAlign: TextAlign.center, style: const TextStyle(color: Colors.black54)),
            const SizedBox(height: 24),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: brandRed,
                minimumSize: const Size.fromHeight(52),
              ),
              onPressed: onRetry,
              child: const Text('Повторить'),
            ),
            const SizedBox(height: 8),
            TextButton(onPressed: onEditUrl, child: const Text('Изменить адрес сервера')),
          ],
        ),
      ),
    );
  }
}

/// Экран выбора адреса сервера: при запуске сборки с ASK_SERVER_URL и по кнопке на экране «нет связи».
class _ServerUrlView extends StatefulWidget {
  const _ServerUrlView({required this.initialUrl, required this.onSubmit});

  final String initialUrl;
  final ValueChanged<String> onSubmit;

  @override
  State<_ServerUrlView> createState() => _ServerUrlViewState();
}

class _ServerUrlViewState extends State<_ServerUrlView> {
  late final TextEditingController _input = TextEditingController(text: widget.initialUrl);
  String? _error;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _submit() {
    final url = normalizeServerUrl(_input.text);
    if (url == null) {
      setState(() => _error = 'Введите адрес, например http://192.168.0.10:8000');
      return;
    }
    widget.onSubmit(url);
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.dns_rounded, size: 72, color: brandRed),
            const SizedBox(height: 16),
            const Text(
              'Адрес сервера',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: brandInk),
            ),
            const SizedBox(height: 8),
            const Text(
              'Какой адрес открыть в приложении?',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.black54),
            ),
            const SizedBox(height: 24),
            TextField(
              controller: _input,
              keyboardType: TextInputType.url,
              textInputAction: TextInputAction.go,
              autocorrect: false,
              onSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                border: const OutlineInputBorder(),
                hintText: 'http://192.168.0.10:8000',
                errorText: _error,
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: brandRed,
                minimumSize: const Size.fromHeight(52),
              ),
              onPressed: _submit,
              child: const Text('Открыть'),
            ),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () => setState(() {
                _input.text = defaultServerUrl;
                _error = null;
              }),
              child: const Text('Адрес по умолчанию'),
            ),
          ],
        ),
      ),
    );
  }
}
