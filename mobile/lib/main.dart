// «Ӟеч-а бур-а удмурт кыл?» — Android-приложение.
//
// Вся игра — веб-приложение (Django + Alpine.js), открытое во WebView. Чтобы оно работало без
// интернета, WebView получает страницы, словарь и картинки не из сети, а из офлайн-снимка
// (assets APK или скачанное обновление, см. bundle.dart). Адрес при этом остаётся настоящим
// (https://hakaton.marshmeg.ru/…), поэтому прогресс в localStorage и вход в облачный аккаунт
// работают одинаково онлайн и офлайн. В сеть уходят только /api/ (синхронизация) и /admin/.
// Мост для JS (резервная копия прогресса, уведомления, геолокация, «поделиться») — bridge.dart.

import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'bridge.dart';
import 'bundle.dart';

/// Адрес сервера задаётся при сборке: flutter build apk --dart-define=SERVER_URL=https://...
/// Для локального сервера в эмуляторе: --dart-define=SERVER_URL=http://10.0.2.2:8000
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://hakaton.marshmeg.ru');

/// Сборка «с выбором адреса»: --dart-define=ASK_SERVER_URL=true. При каждом запуске приложение
/// сначала спрашивает, какой адрес открыть (для проверки на локальном или тестовом сервере).
/// Офлайн-снимок при этом отдаётся по выбранному адресу.
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

/// Пути, которые всегда идут в сеть, даже если такой файл есть в снимке.
const _networkOnly = ['/api/', '/admin/', '/bundle/'];

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
      title: 'Ӟеч-а бур-а удмурт кыл?',
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
  Uri _server = Uri.parse(defaultServerUrl);
  InAppWebViewController? _controller;
  Bundle? _bundle;
  Bridge? _bridge;
  double _progress = 0;
  String? _error;
  bool _asking = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final prefs = await SharedPreferences.getInstance();
    _server = Uri.parse(prefs.getString(_prefsKey) ?? defaultServerUrl);
    final bundle = await Bundle.load();
    if (!mounted) return;
    setState(() {
      _bundle = bundle;
      _bridge = Bridge(bundle);
      _asking = askServerUrl;
    });
    // Новая версия снимка качается в фоне и включится при следующем запуске.
    if (!askServerUrl) bundle.update(_server);
  }

  Future<void> _applyServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, url);
    setState(() {
      _server = Uri.parse(url);
      _asking = false;
      _error = null;
    });
    _bundle?.update(_server);
    _controller?.loadUrl(urlRequest: URLRequest(url: WebUri(_server.resolve('/').toString())));
  }

  /// Ответ на запрос WebView из снимка. null — пусть WebView идёт в сеть.
  Future<WebResourceResponse?> _intercept(WebResourceRequest request) async {
    final bundle = _bundle;
    final url = request.url;
    if (bundle == null || url.origin != _server.origin) return null;
    if ((request.method ?? 'GET').toUpperCase() != 'GET') return null;
    if (_networkOnly.any(url.path.startsWith)) return null;
    final file = bundle.lookup(url.path);
    if (file == null) return null;
    final data = await bundle.read(file.sha);
    if (data == null) return null;
    final parts = file.type.split(';');
    final charset = parts.length > 1 ? parts[1].split('=').last.trim() : null;
    return WebResourceResponse(
      contentType: parts.first.trim(),
      contentEncoding: charset,
      data: data,
      statusCode: 200,
      reasonPhrase: 'OK',
      headers: {'Cache-Control': 'no-store'},
    );
  }

  void _reload() {
    setState(() => _error = null);
    _controller?.loadUrl(urlRequest: URLRequest(url: WebUri(_server.resolve('/').toString())));
  }

  @override
  Widget build(BuildContext context) {
    final bundle = _bundle;
    // Системная кнопка «назад» сначала листает историю WebView и только потом закрывает приложение.
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final navigator = Navigator.of(context);
        final controller = _controller;
        if (controller != null && await controller.canGoBack()) {
          await controller.goBack();
        } else {
          navigator.maybePop();
        }
      },
      child: Scaffold(
        body: SafeArea(
          child: bundle == null
              ? const Center(child: CircularProgressIndicator(color: brandRed))
              : _asking
              ? _ServerUrlView(initialUrl: _server.toString(), onSubmit: _applyServerUrl)
              : Stack(
                  children: [
                    InAppWebView(
                      initialUrlRequest: URLRequest(url: WebUri(_server.resolve('/').toString())),
                      initialSettings: InAppWebViewSettings(
                        useShouldInterceptRequest: true,
                        javaScriptEnabled: true,
                        domStorageEnabled: true,
                        mediaPlaybackRequiresUserGesture: false,
                        transparentBackground: true,
                        supportZoom: false,
                      ),
                      onWebViewCreated: (controller) {
                        _controller = controller;
                        _bridge!.attach(controller);
                      },
                      shouldInterceptRequest: (controller, request) => _intercept(request),
                      onProgressChanged: (controller, progress) =>
                          setState(() => _progress = progress / 100),
                      onReceivedError: (controller, request, error) {
                        // Ошибки картинок и /api/ не мешают игре — реагируем только на саму страницу.
                        if (request.isForMainFrame ?? true) {
                          setState(() => _error = error.description);
                        }
                      },
                    ),
                    if (_progress < 1) LinearProgressIndicator(value: _progress, color: brandRed, minHeight: 3),
                    if (_error != null)
                      _ErrorView(
                        message: _error!,
                        onRetry: _reload,
                        onEditUrl: () => setState(() => _asking = true),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

/// Показывается, только если страницы нет в снимке и нет сети (например, сборка без снимка).
class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry, required this.onEditUrl});

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onEditUrl;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: brandPaper,
      alignment: Alignment.center,
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.wifi_off_rounded, size: 72, color: brandRed),
          const SizedBox(height: 16),
          const Text(
            'Страница не открылась',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: brandInk),
          ),
          const SizedBox(height: 8),
          Text(message, textAlign: TextAlign.center, style: const TextStyle(color: Colors.black54)),
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
