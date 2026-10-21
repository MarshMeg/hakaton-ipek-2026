// «Ӟеч-а бур-а удмурт кыл?» — Android-приложение.
//
// Вся игра — веб-приложение (Django + Alpine.js), открытое во WebView. Чтобы оно работало без
// интернета, WebView получает страницы, словарь и картинки не из сети, а из офлайн-снимка
// (assets APK или скачанное обновление, см. bundle.dart). Адрес при этом остаётся настоящим
// (https://hakaton.marshmeg.ru/…), поэтому прогресс в localStorage и вход в облачный аккаунт
// работают одинаково онлайн и офлайн. В сеть уходят только /api/ (вход и сохранение) и /admin/.
// Мост для JS (резервная копия прогресса, уведомления, геолокация, «поделиться») — bridge.dart.
//
// Запуск: загрузить снимок → проверить обновление снимка (не дольше [updateBudget], без сети —
// сразу дальше) → открыть WebView. Вход и синхронизация сохранения — уже в JS (app.js).

import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

import 'bridge.dart';
import 'bundle.dart';

/// Адрес сервера задаётся при сборке: flutter build apk --dart-define=SERVER_URL=https://...
/// Для локального сервера в эмуляторе: --dart-define=SERVER_URL=http://10.0.2.2:8000
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://hakaton.marshmeg.ru');

/// Сколько ждать обновления снимка при запуске, прежде чем открыть игру на текущем.
const Duration updateBudget = Duration(seconds: 20);

/// Метка в User-Agent: по ней JS понимает, что открыт в приложении и стоит ждать мост.
const String userAgentMark = 'VotesApp';

/// Пути, которые всегда идут в сеть, даже если такой файл есть в снимке.
const _networkOnly = ['/api/', '/admin/', '/bundle/'];

/// Отдавать ли запрос WebView из снимка: только GET к нашему серверу [server], кроме [_networkOnly].
/// Чужие адреса, POST/PUT к /api/ и т. п. уходят в сеть как обычно.
bool servedFromBundle(Uri url, String? method, Uri server) {
  if (url.origin != server.origin) return false;
  if ((method ?? 'GET').toUpperCase() != 'GET') return false;
  return !_networkOnly.any(url.path.startsWith);
}

/// Делит тип из манифеста («text/html; charset=utf-8») на MIME-тип и кодировку:
/// WebResourceResponse принимает их отдельно (кодировка у Android называется contentEncoding).
({String mime, String? charset}) splitContentType(String type) {
  final parts = type.split(';');
  final charset = parts.length > 1 ? parts[1].split('=').last.trim() : null;
  return (mime: parts.first.trim(), charset: charset);
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

/// Единственный экран приложения: сначала заставка, пока грузится и обновляется снимок,
/// потом WebView с игрой на весь экран.
class _GameScreenState extends State<GameScreen> {
  final Uri _server = Uri.parse(defaultServerUrl);
  InAppWebViewController? _controller;
  Bundle? _bundle;
  Bridge? _bridge;
  double _progress = 0;
  String? _error;
  // true, пока идёт проверка обновления снимка — в это время показываем заставку.
  bool _updating = true;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final bundle = await Bundle.load();
    if (!mounted) return;
    setState(() {
      _bundle = bundle;
      _bridge = Bridge(bundle);
    });
    await _updateBundle();
  }

  /// Шаги 1–2 цикла запуска: новая версия снимка включается сразу, до показа WebView.
  Future<void> _updateBundle() async {
    final bundle = _bundle!;
    setState(() => _updating = true);
    try {
      await bundle.update(_server).timeout(updateBudget);
    } catch (_) {
      // Тайм-аут: обновление докачается в фоне и включится при следующем запуске.
    }
    bundle.freeze();
    if (mounted) setState(() => _updating = false);
  }

  /// Ответ на запрос WebView из снимка. null — пусть WebView идёт в сеть
  /// (запрос не для снимка или такого файла в снимке нет).
  Future<WebResourceResponse?> _intercept(WebResourceRequest request) async {
    final bundle = _bundle;
    if (bundle == null || !servedFromBundle(request.url, request.method, _server)) return null;
    final file = bundle.lookup(request.url.path);
    if (file == null) return null;
    final data = await bundle.read(file.sha);
    if (data == null) return null;
    final type = splitContentType(file.type);
    return WebResourceResponse(
      contentType: type.mime,
      contentEncoding: type.charset,
      data: data,
      statusCode: 200,
      reasonPhrase: 'OK',
      // Кэш WebView не нужен (файлы и так на телефоне), а после обновления снимка он отдал
      // бы старую версию страницы.
      headers: {'Cache-Control': 'no-store'},
    );
  }

  // Главная страница игры на нашем сервере.
  URLRequest get _homeRequest => URLRequest(url: WebUri(_server.resolve('/').toString()));

  // Кнопка «Повторить» на экране ошибки: заново открываем главную.
  void _reload() {
    setState(() => _error = null);
    _controller?.loadUrl(urlRequest: _homeRequest);
  }

  // Системная кнопка «назад» сначала листает историю WebView и только потом закрывает приложение.
  Future<void> _onBack(bool didPop) async {
    if (didPop) return;
    final navigator = Navigator.of(context);
    final controller = _controller;
    if (controller != null && await controller.canGoBack()) {
      await controller.goBack();
    } else {
      navigator.maybePop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) => _onBack(didPop),
      child: Scaffold(body: SafeArea(child: _buildBody())),
    );
  }

  Widget _buildBody() {
    if (_bundle == null) return const _SplashView(text: 'Загрузка…');
    if (_updating) return const _SplashView(text: 'Проверяем обновления…');
    return Stack(
      children: [
        _buildWebView(),
        if (_progress < 1) LinearProgressIndicator(value: _progress, color: brandRed, minHeight: 3),
        if (_error != null) _ErrorView(message: _error!, onRetry: _reload),
      ],
    );
  }

  Widget _buildWebView() {
    return InAppWebView(
      initialUrlRequest: _homeRequest,
      // useShouldInterceptRequest — без него _intercept не вызывается, и всё
      // шло бы в сеть. applicationNameForUserAgent дописывает VotesApp в UA.
      initialSettings: InAppWebViewSettings(
        useShouldInterceptRequest: true,
        javaScriptEnabled: true,
        domStorageEnabled: true,
        mediaPlaybackRequiresUserGesture: false,
        transparentBackground: true,
        supportZoom: false,
        applicationNameForUserAgent: userAgentMark,
      ),
      onWebViewCreated: (controller) {
        _controller = controller;
        _bridge!.attach(controller);
      },
      shouldInterceptRequest: (controller, request) => _intercept(request),
      onProgressChanged: (controller, progress) => setState(() => _progress = progress / 100),
      onReceivedError: (controller, request, error) {
        // Ошибки картинок и /api/ не мешают игре — реагируем только на саму страницу.
        if (request.isForMainFrame ?? true) {
          setState(() => _error = error.description);
        }
      },
    );
  }
}

/// Заставка при запуске: пока загружается и обновляется офлайн-снимок.
class _SplashView extends StatelessWidget {
  const _SplashView({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(28),
            child: Image.asset('assets/icon/icon.png', width: 112, height: 112),
          ),
          const SizedBox(height: 24),
          const SizedBox(
            width: 160,
            child: LinearProgressIndicator(color: brandRed, backgroundColor: Color(0x33C8102E)),
          ),
          const SizedBox(height: 16),
          Text(
            text,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: brandInk),
          ),
        ],
      ),
    );
  }
}

/// Показывается, только если страницы нет в снимке и нет сети (например, первый запуск без интернета).
class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

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
        ],
      ),
    );
  }
}
