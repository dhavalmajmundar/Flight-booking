import 'package:flutter/material.dart';
import '../api_client.dart';

class WatchesScreen extends StatefulWidget {
  const WatchesScreen({super.key, required this.api});
  final FlightApi api;
  @override
  State<WatchesScreen> createState() => _WatchesScreenState();
}

class _WatchesScreenState extends State<WatchesScreen> {
  bool loading = true;
  List<Map<String, dynamic>> watches = [];
  Map<String, dynamic> profile = {};
  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    setState(() => loading = true);
    try {
      final values = await Future.wait([
        widget.api.get('/watches'),
        widget.api.get('/profile'),
      ]);
      watches = List<Map<String, dynamic>>.from(
        (values[0] as List).map((e) => Map<String, dynamic>.from(e)),
      );
      profile = Map<String, dynamic>.from(values[1]);
    } catch (e) {
      _message(e.toString());
    }
    if (mounted) setState(() => loading = false);
  }

  void _message(String value) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(value)));
  Future<void> _action(String path, {String success = 'Done.'}) async {
    try {
      await widget.api.post(path);
      _message(success);
      await refresh();
    } catch (e) {
      _message(e.toString());
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
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
                        'Price watches',
                        style: Theme.of(context).textTheme.headlineMedium
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const Text(
                        'Persistent, owner-only monitoring within the Railway daily cap.',
                      ),
                    ],
                  ),
                ),
                FilledButton.icon(
                  onPressed: () async {
                    final changed = await showDialog<bool>(
                      context: context,
                      builder: (_) =>
                          _WatchDialog(api: widget.api, profile: profile),
                    );
                    if (changed == true) refresh();
                  },
                  icon: const Icon(Icons.add_alert),
                  label: const Text('New watch'),
                ),
              ],
            ),
            const SizedBox(height: 16),
            if (loading) const LinearProgressIndicator(),
            if (!loading && watches.isEmpty)
              const Expanded(
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.notifications_none_rounded,
                        size: 72,
                        color: Colors.blueGrey,
                      ),
                      SizedBox(height: 12),
                      Text('No active watches'),
                      Text(
                        'Create one to monitor a route without repeatedly searching manually.',
                      ),
                    ],
                  ),
                ),
              ),
            if (watches.isNotEmpty)
              Expanded(
                child: RefreshIndicator(
                  onRefresh: refresh,
                  child: ListView.builder(
                    itemCount: watches.length,
                    itemBuilder: (context, index) => _watchCard(watches[index]),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );

  Widget _watchCard(Map<String, dynamic> watch) => Card(
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(child: Text('${indexOf(watch) + 1}')),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${watch['origin']} → ${watch['destination']}',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      '${watch['departure_date']}${watch['return_date'] == null ? ' · one-way' : ' → ${watch['return_date']}'} · ${watch['adults']} adult(s) · ${watch['cabin'].toString().replaceAll('_', ' ')}',
                    ),
                  ],
                ),
              ),
              Text(
                watch['last_price'] == null
                    ? 'Awaiting baseline'
                    : '${watch['currency']} ${(watch['last_price'] as num).toStringAsFixed(2)}',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Theme.of(context).colorScheme.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Chip(label: Text('ID ${watch['short_id']}')),
              Chip(label: Text('Every ${watch['interval_hours']}h')),
              Chip(label: Text('Drop ${watch['drop_percent']}%')),
              Chip(
                label: Text(
                  watch['target_price'] == null
                      ? 'No target'
                      : 'Target ${watch['currency']} ${watch['target_price']}',
                ),
              ),
              Chip(
                avatar: Icon(
                  watch['weekly_flex'] ? Icons.date_range : Icons.event_busy,
                  size: 18,
                ),
                label: Text('Weekly ±3 ${watch['weekly_flex'] ? 'on' : 'off'}'),
              ),
              if ((watch['consecutive_failures'] ?? 0) > 0)
                Chip(
                  backgroundColor: Colors.amber.shade50,
                  label: Text(
                    '${watch['consecutive_failures']} unavailable check(s)',
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: () => _action(
                  '/watches/${watch['short_id']}/check',
                  success: 'A capped check was queued.',
                ),
                icon: const Icon(Icons.refresh),
                label: const Text('Check now'),
              ),
              OutlinedButton.icon(
                onPressed: () => _history(watch),
                icon: const Icon(Icons.show_chart),
                label: const Text('History'),
              ),
              OutlinedButton.icon(
                onPressed: () => _action(
                  '/watches/${watch['short_id']}/booked',
                  success: 'Marked booked and stopped.',
                ),
                icon: const Icon(Icons.check_circle_outline),
                label: const Text('Mark booked'),
              ),
              TextButton.icon(
                onPressed: () async {
                  final yes = await _confirm(
                    'Stop this watch?',
                    'Its history remains in your export.',
                  );
                  if (yes) {
                    try {
                      await widget.api.delete('/watches/${watch['short_id']}');
                      await refresh();
                    } catch (e) {
                      _message(e.toString());
                    }
                  }
                },
                icon: const Icon(Icons.stop_circle_outlined),
                label: const Text('Stop'),
              ),
            ],
          ),
        ],
      ),
    ),
  );

  int indexOf(Map<String, dynamic> watch) =>
      watches.indexWhere((item) => item['id'] == watch['id']);
  Future<bool> _confirm(String title, String body) async =>
      await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Confirm'),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _history(Map<String, dynamic> watch) async {
    try {
      final data = List<Map<String, dynamic>>.from(
        (await widget.api.get('/watches/${watch['short_id']}/history') as List)
            .map((e) => Map<String, dynamic>.from(e)),
      );
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          title: Text('${watch['origin']} → ${watch['destination']} history'),
          content: SizedBox(
            width: 560,
            height: 300,
            child: data.isEmpty
                ? const Center(child: Text('No observations yet.'))
                : Column(
                    children: [
                      Expanded(
                        child: CustomPaint(
                          painter: _PriceChart(
                            data
                                .map((e) => (e['price'] as num).toDouble())
                                .toList(),
                          ),
                          child: const SizedBox.expand(),
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '${data.length} observation(s) · Low ${watch['currency']} ${data.map((e) => e['price'] as num).reduce((a, b) => a < b ? a : b).toStringAsFixed(2)}',
                      ),
                    ],
                  ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } catch (e) {
      _message(e.toString());
    }
  }
}

class _WatchDialog extends StatefulWidget {
  const _WatchDialog({required this.api, required this.profile});
  final FlightApi api;
  final Map<String, dynamic> profile;
  @override
  State<_WatchDialog> createState() => _WatchDialogState();
}

class _WatchDialogState extends State<_WatchDialog> {
  final origin = TextEditingController(),
      destination = TextEditingController(),
      target = TextEditingController();
  DateTime departure = DateTime.now().add(const Duration(days: 45));
  bool roundTrip = true, weekly = false, saving = false;
  int tripDays = 7, drop = 5, interval = 24, lifetime = 30;
  String date(DateTime value) => value.toIso8601String().split('T').first;
  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Create price watch'),
    content: SizedBox(
      width: 650,
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Setup uses no RouteStack call. The baseline is queued only after confirmation.',
            ),
            const SizedBox(height: 14),
            TextField(
              controller: origin,
              decoration: const InputDecoration(
                labelText: 'From city or airport',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: destination,
              decoration: const InputDecoration(
                labelText: 'To city or airport',
              ),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: () async {
                final picked = await showDatePicker(
                  context: context,
                  firstDate: DateTime.now(),
                  lastDate: DateTime.now().add(const Duration(days: 730)),
                  initialDate: departure,
                );
                if (picked != null) setState(() => departure = picked);
              },
              icon: const Icon(Icons.calendar_month),
              label: Text('Departure ${date(departure)}'),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Round trip · default'),
              value: roundTrip,
              onChanged: (v) => setState(() => roundTrip = v),
            ),
            if (roundTrip)
              DropdownButtonFormField<int>(
                initialValue: tripDays,
                decoration: const InputDecoration(labelText: 'Trip duration'),
                items: [3, 5, 7, 10, 14, 21, 30]
                    .map(
                      (v) => DropdownMenuItem(
                        value: v,
                        child: Text('$v days${v == 7 ? ' · default' : ''}'),
                      ),
                    )
                    .toList(),
                onChanged: (v) => setState(() => tripDays = v!),
              ),
            const SizedBox(height: 10),
            TextField(
              controller: target,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText:
                    'Target total (${widget.profile['currency'] ?? 'USD'})',
                hintText: 'No target · default',
              ),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<int>(
              initialValue: drop,
              decoration: const InputDecoration(labelText: 'Meaningful drop'),
              items: [3, 5, 10, 15]
                  .map(
                    (v) => DropdownMenuItem(
                      value: v,
                      child: Text('$v%${v == 5 ? ' · default' : ''}'),
                    ),
                  )
                  .toList(),
              onChanged: (v) => setState(() => drop = v!),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<int>(
              initialValue: interval,
              decoration: const InputDecoration(labelText: 'Base frequency'),
              items: [6, 12, 24, 48]
                  .map(
                    (v) => DropdownMenuItem(
                      value: v,
                      child: Text('Every ${v}h${v == 24 ? ' · default' : ''}'),
                    ),
                  )
                  .toList(),
              onChanged: (v) => setState(() => interval = v!),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<int>(
              initialValue: lifetime,
              decoration: const InputDecoration(labelText: 'Watch lifetime'),
              items: [7, 14, 30, 60]
                  .map(
                    (v) => DropdownMenuItem(
                      value: v,
                      child: Text('$v days${v == 30 ? ' · default' : ''}'),
                    ),
                  )
                  .toList(),
              onChanged: (v) => setState(() => lifetime = v!),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Weekly ±3-day deep scan'),
              subtitle: const Text(
                'Off by default; may use up to 7 capped calls once weekly.',
              ),
              value: weekly,
              onChanged: (v) => setState(() => weekly = v),
            ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: saving ? null : () => Navigator.pop(context, false),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: saving ? null : _save,
        child: Text(saving ? 'Saving…' : 'Create watch'),
      ),
    ],
  );

  Future<void> _save() async {
    if (origin.text.trim().length < 2 || destination.text.trim().length < 2) {
      return;
    }
    setState(() => saving = true);
    final p = widget.profile;
    final trip = {
      'origin': origin.text.trim(),
      'destination': destination.text.trim(),
      'departure_date': date(departure),
      'return_date': roundTrip
          ? date(departure.add(Duration(days: tripDays)))
          : null,
      'adults': p['adults'] ?? 4,
      'cabin': p['cabin'] ?? 'ECONOMY',
      'flexible_dates': false,
      'flexible_days': 0,
      'nearby_mode': 'no',
      'checked_bags': p['checked_bags'] ?? 2,
      'carry_on_bags': p['carry_on_bags'] ?? 1,
      'preferred_airlines': p['preferred_airlines'] ?? [],
      'avoided_airlines': p['avoided_airlines'] ?? [],
      'priority': 'cheapest',
      'currency': p['currency'] ?? 'USD',
      'departure_window': p['departure_window'] ?? 'any',
      'avoid_red_eye': p['avoid_red_eye'] ?? true,
      'max_stops': p['max_stops'],
      'min_layover_minutes': p['min_layover_minutes'] ?? 60,
      'max_layover_minutes': p['max_layover_minutes'] ?? 300,
      'max_total_duration_minutes': p['max_total_duration_minutes'],
      'search_mode': 'exact',
    };
    final watchSettings = {
      'target_price': double.tryParse(target.text),
      'drop_percent': drop,
      'interval_hours': interval,
      'duration_days': lifetime,
      'weekly_flex': weekly,
    };
    try {
      await widget.api.post('/watches', {'trip': trip, ...watchSettings});
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (e.statusCode == 409 && mounted) {
        final existing =
            List<Map<String, dynamic>>.from(
                  (await widget.api.get('/watches') as List).map(
                    (item) => Map<String, dynamic>.from(item),
                  ),
                )
                .where(
                  (item) =>
                      item['origin'].toString().toLowerCase() ==
                          origin.text.trim().toLowerCase() &&
                      item['destination'].toString().toLowerCase() ==
                          destination.text.trim().toLowerCase() &&
                      item['departure_date'] == date(departure),
                )
                .toList();
        if (!mounted) return;
        final update = existing.isNotEmpty
            ? await showDialog<bool>(
                context: context,
                builder: (dialogContext) => AlertDialog(
                  title: const Text('Duplicate watch found'),
                  content: Text(
                    'Watch ${existing.first['short_id']} already monitors this trip. Update its target and schedule instead of using another slot?',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      child: const Text('Keep existing'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.pop(dialogContext, true),
                      child: const Text('Update existing'),
                    ),
                  ],
                ),
              )
            : false;
        if (!mounted) return;
        if (update == true) {
          await widget.api.put(
            '/watches/${existing.first['short_id']}',
            watchSettings,
          );
          if (mounted) Navigator.pop(context, true);
          return;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('The existing watch was left unchanged.'),
          ),
        );
      } else if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.message)));
      }
      if (mounted) setState(() => saving = false);
    }
  }
}

class _PriceChart extends CustomPainter {
  _PriceChart(this.values);
  final List<double> values;
  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = Colors.blueGrey.shade100
      ..strokeWidth = 1;
    for (var i = 0; i <= 4; i++) {
      final y = size.height * i / 4;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    if (values.length < 2) return;
    final low = values.reduce((a, b) => a < b ? a : b),
        high = values.reduce((a, b) => a > b ? a : b);
    final range = high == low ? 1 : high - low;
    final path = Path();
    for (var i = 0; i < values.length; i++) {
      final point = Offset(
        size.width * i / (values.length - 1),
        size.height - ((values[i] - low) / range * (size.height - 20)) - 10,
      );
      if (i == 0) {
        path.moveTo(point.dx, point.dy);
      } else {
        path.lineTo(point.dx, point.dy);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xFF2563EB)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(covariant _PriceChart oldDelegate) =>
      oldDelegate.values != values;
}
