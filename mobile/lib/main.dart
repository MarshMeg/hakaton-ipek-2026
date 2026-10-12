// Вотэс — Android-приложение. Вся игра работает на сервере (Django) и открывается во WebView;
// приложение отвечает за запуск, экран «нет связи», кнопку «назад» и выбор адреса сервера.

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// Адрес по умолчанию задаётся при сборке: flutter build apk --dart-define=SERVER_URL=https://...
/// Для локального сервера в эмуляторе: --dart-define=SERVER_URL=http://10.0.2.2:8000
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://hakaton.marshmeg.ru');

const String _prefsKey = 'server_url';

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
    _loadSavedUrl();
  }

  Future<void> _loadSavedUrl() async {
    final prefs = await SharedPreferences.getInstance();
    _serverUrl = prefs.getString(_prefsKey) ?? defaultServerUrl;
    _open();
  }

  void _open() {
    setState(() {
      _offline = false;
      _loading = true;
    });
    _controller.loadRequest(Uri.parse(_serverUrl));
  }

  Future<void> _editServerUrl() async {
    final input = TextEditingController(text: _serverUrl);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Адрес сервера'),
        content: TextField(
          controller: input,
          keyboardType: TextInputType.url,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'http://192.168.0.10:8000'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, defaultServerUrl),
            child: const Text('По умолчанию'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, input.text.trim()),
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    if (result == null || result.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, result);
    _serverUrl = result;
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
          child: _offline
              ? _OfflineView(
                  serverUrl: _serverUrl,
                  onRetry: _open,
                  onEditUrl: _editServerUrl,
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
