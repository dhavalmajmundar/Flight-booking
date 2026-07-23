import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_client.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.api});
  final FlightApi api;
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  bool loading = true;
  Map<String, dynamic> health = {}, usage = {};
  List<Map<String, dynamic>> deals = [], cleanup = [];
  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    setState(() => loading = true);
    try {
      final data = await Future.wait([
        widget.api.get('/health'),
        widget.api.get('/usage'),
        widget.api.get('/deals'),
        widget.api.get('/cleanup'),
      ]);
      health = Map<String, dynamic>.from(data[0]);
      usage = Map<String, dynamic>.from(data[1]);
      deals = List<Map<String, dynamic>>.from(
        (data[2] as List).map((e) => Map<String, dynamic>.from(e)),
      );
      cleanup = List<Map<String, dynamic>>.from(
        (data[3] as List).map((e) => Map<String, dynamic>.from(e)),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) => RefreshIndicator(
    onRefresh: refresh,
    child: SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Owner dashboard',
                          style: Theme.of(context).textTheme.headlineMedium
                              ?.copyWith(fontWeight: FontWeight.bold),
                        ),
                        const Text(
                          'Health, call budget, deal ranking, cleanup, and backup—all without a fare search.',
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: refresh,
                    icon: const Icon(Icons.refresh),
                    tooltip: 'Refresh',
                  ),
                ],
              ),
              if (loading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: LinearProgressIndicator(),
                ),
              const SizedBox(height: 12),
              LayoutBuilder(
                builder: (context, size) {
                  final width = size.maxWidth > 800
                      ? (size.maxWidth - 32) / 3
                      : size.maxWidth;
                  return Wrap(
                    spacing: 16,
                    runSpacing: 16,
                    children: [
                      _Metric(
                        width: width,
                        icon: Icons.cloud_done_outlined,
                        title: 'Services',
                        value: health['database'] == true
                            ? 'Connected'
                            : 'Needs attention',
                        detail:
                            'API ${health['ok'] == true ? 'online' : 'offline'} · RouteStack ${health['route_stack'] == true ? 'configured' : 'missing'}',
                      ),
                      _Metric(
                        width: width,
                        icon: Icons.token_outlined,
                        title: 'Watch calls today',
                        value:
                            '${usage['used_today'] ?? 0} / ${usage['daily_cap'] ?? '—'}',
                        detail:
                            'Forecast ${(usage['projected_weekly'] as num?)?.toStringAsFixed(0) ?? '—'} calls/week',
                      ),
                      _Metric(
                        width: width,
                        icon: Icons.notifications_active_outlined,
                        title: 'Active watches',
                        value:
                            '${usage['active'] ?? 0} / ${usage['active_cap'] ?? '—'}',
                        detail: 'Hard cap prevents unexpected monitoring use',
                      ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 22),
              _Header('Best stored deals', Icons.local_offer_outlined),
              if (deals.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(20),
                    child: Text('No priced active watches yet.'),
                  ),
                ),
              ...deals
                  .take(5)
                  .map(
                    (watch) => Card(
                      child: ListTile(
                        leading: const CircleAvatar(child: Icon(Icons.flight)),
                        title: Text(
                          '${watch['origin']} → ${watch['destination']}',
                        ),
                        subtitle: Text(
                          '${watch['departure_date']} · ID ${watch['short_id']}',
                        ),
                        trailing: Text(
                          '${watch['currency']} ${(watch['last_price'] as num).toStringAsFixed(2)}',
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                    ),
                  ),
              const SizedBox(height: 18),
              _Header('Cleanup suggestions', Icons.cleaning_services_outlined),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: cleanup.isEmpty
                      ? const Text(
                          'Everything looks clean. No stale watches detected.',
                        )
                      : Column(
                          children: cleanup
                              .map(
                                (watch) => ListTile(
                                  leading: const Icon(Icons.warning_amber),
                                  title: Text(
                                    '${watch['origin']} → ${watch['destination']}',
                                  ),
                                  subtitle: Text(
                                    '${watch['consecutive_failures']} unavailable checks · use Watches to stop or mark booked',
                                  ),
                                ),
                              )
                              .toList(),
                        ),
                ),
              ),
              const SizedBox(height: 18),
              _Header('Private backup', Icons.backup_outlined),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Copy a JSON backup of your profile, watches, and observed prices. Credentials are excluded.',
                        ),
                      ),
                      FilledButton.icon(
                        onPressed: _export,
                        icon: const Icon(Icons.copy_all_outlined),
                        label: const Text('Copy JSON backup'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    ),
  );

  Future<void> _export() async {
    try {
      final data = await widget.api.get('/export');
      await Clipboard.setData(
        ClipboardData(text: const JsonEncoder.withIndent('  ').convert(data)),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Private JSON backup copied to the clipboard.'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    }
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.width,
    required this.icon,
    required this.title,
    required this.value,
    required this.detail,
  });
  final double width;
  final IconData icon;
  final String title, value, detail;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: width,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: Theme.of(context).colorScheme.primary, size: 30),
            const SizedBox(height: 12),
            Text(title),
            Text(
              value,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
            ),
            Text(detail, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    ),
  );
}

class _Header extends StatelessWidget {
  const _Header(this.text, this.icon);
  final String text;
  final IconData icon;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        Icon(icon),
        const SizedBox(width: 8),
        Text(
          text,
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
        ),
      ],
    ),
  );
}
