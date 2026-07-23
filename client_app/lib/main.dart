import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'screens/dashboard_screen.dart';
import 'screens/search_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/watches_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const FlightCompanionApp());
}

class FlightCompanionApp extends StatefulWidget {
  const FlightCompanionApp({super.key});
  @override
  State<FlightCompanionApp> createState() => _FlightCompanionAppState();
}

class _FlightCompanionAppState extends State<FlightCompanionApp> {
  static const _secure = FlutterSecureStorage();
  FlightApi? api;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString('api_url') ?? '';
    final token = await _secure.read(key: 'api_token') ?? '';
    if (url.isNotEmpty && token.isNotEmpty) {
      api = FlightApi(baseUrl: url, token: token);
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> configure(String url, String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_url', url.trim());
    await _secure.write(key: 'api_token', value: token.trim());
    setState(() => api = FlightApi(baseUrl: url.trim(), token: token.trim()));
  }

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF2563EB),
      brightness: Brightness.light,
      surface: const Color(0xFFF8FAFC),
    );
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Flight Companion',
      theme: ThemeData(
        colorScheme: scheme,
        useMaterial3: true,
        scaffoldBackgroundColor: scheme.surface,
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          filled: true,
          fillColor: Colors.white,
        ),
        cardTheme: CardThemeData(
          elevation: 0,
          color: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
            side: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
        ),
      ),
      home: loading
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : api == null
          ? ConnectionSetup(onSave: configure)
          : AppShell(api: api!, onConfigure: configure),
    );
  }
}

class ConnectionSetup extends StatefulWidget {
  const ConnectionSetup({super.key, required this.onSave});
  final Future<void> Function(String, String) onSave;
  @override
  State<ConnectionSetup> createState() => _ConnectionSetupState();
}

class _ConnectionSetupState extends State<ConnectionSetup> {
  final url = TextEditingController();
  final token = TextEditingController();
  bool saving = false;

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(
                    Icons.flight_takeoff_rounded,
                    size: 64,
                    color: Color(0xFF2563EB),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Connect Flight Companion',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Enter your public Railway service URL and the private APP_ACCESS_TOKEN. RouteStack and database credentials remain safely on Railway.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    controller: url,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(
                      labelText: 'Railway URL',
                      hintText: 'https://your-service.up.railway.app',
                      prefixIcon: Icon(Icons.cloud_outlined),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: token,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'App access token',
                      prefixIcon: Icon(Icons.key_outlined),
                    ),
                  ),
                  const SizedBox(height: 22),
                  FilledButton.icon(
                    onPressed: saving
                        ? null
                        : () async {
                            if (!url.text.startsWith('https://') ||
                                token.text.trim().length < 16) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text(
                                    'Use an HTTPS Railway URL and a token of at least 16 characters.',
                                  ),
                                ),
                              );
                              return;
                            }
                            setState(() => saving = true);
                            await widget.onSave(url.text, token.text);
                          },
                    icon: const Icon(Icons.lock_open_rounded),
                    label: const Text('Save secure connection'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class AppShell extends StatefulWidget {
  const AppShell({super.key, required this.api, required this.onConfigure});
  final FlightApi api;
  final Future<void> Function(String, String) onConfigure;
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int index = 0;
  late final pages = [
    SearchScreen(api: widget.api),
    WatchesScreen(api: widget.api),
    DashboardScreen(api: widget.api),
    SettingsScreen(api: widget.api, onConfigure: widget.onConfigure),
  ];
  static const destinations = [
    NavigationDestination(icon: Icon(Icons.search_rounded), label: 'Search'),
    NavigationDestination(
      icon: Icon(Icons.notifications_active_outlined),
      label: 'Watches',
    ),
    NavigationDestination(
      icon: Icon(Icons.dashboard_outlined),
      label: 'Dashboard',
    ),
    NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'Settings'),
  ];

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, size) {
      final wide = size.maxWidth >= 900;
      final body = IndexedStack(index: index, children: pages);
      return Scaffold(
        appBar: AppBar(
          title: const Row(
            children: [
              Icon(Icons.flight_takeoff_rounded),
              SizedBox(width: 10),
              Text('Flight Companion'),
            ],
          ),
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.transparent,
        ),
        body: wide
            ? Row(
                children: [
                  NavigationRail(
                    selectedIndex: index,
                    onDestinationSelected: (value) =>
                        setState(() => index = value),
                    labelType: NavigationRailLabelType.all,
                    destinations: destinations
                        .map(
                          (item) => NavigationRailDestination(
                            icon: item.icon,
                            label: Text(item.label),
                          ),
                        )
                        .toList(),
                  ),
                  const VerticalDivider(width: 1),
                  Expanded(child: body),
                ],
              )
            : body,
        bottomNavigationBar: wide
            ? null
            : NavigationBar(
                selectedIndex: index,
                onDestinationSelected: (value) => setState(() => index = value),
                destinations: destinations,
              ),
      );
    },
  );
}
