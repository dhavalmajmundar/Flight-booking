import 'package:flutter/material.dart';
import '../api_client.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.api,
    required this.onConfigure,
  });
  final FlightApi api;
  final Future<void> Function(String, String) onConfigure;
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final preferred = TextEditingController(),
      avoided = TextEditingController(),
      budget = TextEditingController(),
      timezone = TextEditingController();
  bool loading = true, saving = false, avoidRedEye = true;
  int adults = 4,
      checked = 2,
      carry = 1,
      minLayover = 60,
      maxLayover = 300,
      quietStart = 22,
      quietEnd = 7;
  int? maxStops, maxDuration;
  String cabin = 'ECONOMY', currency = 'USD', window = 'any';
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => loading = true);
    try {
      final p = Map<String, dynamic>.from(await widget.api.get('/profile'));
      adults = p['adults'] ?? 4;
      cabin = p['cabin'] ?? 'ECONOMY';
      checked = p['checked_bags'] ?? 2;
      carry = p['carry_on_bags'] ?? 1;
      currency = p['currency'] ?? 'USD';
      window = p['departure_window'] ?? 'any';
      avoidRedEye = p['avoid_red_eye'] ?? true;
      maxStops = p['max_stops'];
      minLayover = p['min_layover_minutes'] ?? 60;
      maxLayover = p['max_layover_minutes'] ?? 300;
      maxDuration = p['max_total_duration_minutes'];
      quietStart = p['quiet_start_hour'] ?? 22;
      quietEnd = p['quiet_end_hour'] ?? 7;
      preferred.text = (p['preferred_airlines'] as List? ?? []).join(', ');
      avoided.text = (p['avoided_airlines'] as List? ?? []).join(', ');
      budget.text = p['max_budget']?.toString() ?? '';
      timezone.text = p['timezone'] ?? 'America/New_York';
    } catch (e) {
      _message(e.toString());
    }
    if (mounted) setState(() => loading = false);
  }

  List<String> codes(String value) => value
      .split(',')
      .map((e) => e.trim().toUpperCase())
      .where((e) => e.isNotEmpty)
      .toList();
  void _message(String value) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(value)));

  Future<void> save() async {
    setState(() => saving = true);
    try {
      await widget.api.put('/profile', {
        'preferred_airlines': codes(preferred.text),
        'avoided_airlines': codes(avoided.text),
        'max_budget': double.tryParse(budget.text),
        'max_layover_minutes': maxLayover,
        'adults': adults,
        'cabin': cabin,
        'checked_bags': checked,
        'carry_on_bags': carry,
        'currency': currency,
        'departure_window': window,
        'avoid_red_eye': avoidRedEye,
        'max_stops': maxStops,
        'min_layover_minutes': minLayover,
        'max_total_duration_minutes': maxDuration,
        'timezone': timezone.text.trim(),
        'quiet_start_hour': quietStart,
        'quiet_end_hour': quietEnd,
      });
      _message(
        'Profile defaults saved. Guided searches and watches will use them.',
      );
    } catch (e) {
      _message(e.toString());
    }
    if (mounted) setState(() => saving = false);
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.all(20),
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1000),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Defaults & security',
              style: Theme.of(
                context,
              ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
            ),
            const Text(
              'These are owner-only defaults. Every search can still override them.',
            ),
            const SizedBox(height: 16),
            if (loading) const LinearProgressIndicator(),
            _card(
              'Traveler defaults',
              Icons.people_outline,
              Wrap(
                spacing: 14,
                runSpacing: 14,
                children: [
                  _number(
                    'Adults',
                    adults,
                    1,
                    9,
                    (v) => setState(() => adults = v),
                  ),
                  SizedBox(
                    width: 260,
                    child: drop('Cabin', cabin, const {
                      'ECONOMY': 'Economy · default',
                      'PREMIUM_ECONOMY': 'Premium economy',
                      'BUSINESS': 'Business',
                      'FIRST': 'First',
                    }, (v) => setState(() => cabin = v)),
                  ),
                  SizedBox(
                    width: 180,
                    child: drop('Currency', currency, const {
                      'USD': 'USD · default',
                      'CAD': 'CAD',
                      'EUR': 'EUR',
                      'GBP': 'GBP',
                      'INR': 'INR',
                    }, (v) => setState(() => currency = v)),
                  ),
                  _number(
                    'Checked bags',
                    checked,
                    0,
                    2,
                    (v) => setState(() => checked = v),
                  ),
                  _number(
                    'Carry-ons',
                    carry,
                    0,
                    2,
                    (v) => setState(() => carry = v),
                  ),
                ],
              ),
            ),
            _card(
              'Airlines & budget',
              Icons.payments_outlined,
              Wrap(
                spacing: 14,
                runSpacing: 14,
                children: [
                  SizedBox(
                    width: 270,
                    child: TextField(
                      controller: preferred,
                      decoration: const InputDecoration(
                        labelText: 'Preferred airline codes',
                        hintText: 'DL, UA',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 270,
                    child: TextField(
                      controller: avoided,
                      decoration: const InputDecoration(
                        labelText: 'Airlines to avoid',
                        hintText: 'NK, F9',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 240,
                    child: TextField(
                      controller: budget,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                        labelText: 'Default total budget ($currency)',
                        hintText: 'No maximum',
                      ),
                    ),
                  ),
                ],
              ),
            ),
            _card(
              'Comfort defaults',
              Icons.airline_seat_recline_extra_outlined,
              Wrap(
                spacing: 14,
                runSpacing: 14,
                children: [
                  SizedBox(
                    width: 230,
                    child: drop('Departure window', window, const {
                      'any': 'Any · default',
                      'morning': 'Morning',
                      'afternoon': 'Afternoon',
                      'evening': 'Evening',
                    }, (v) => setState(() => window = v)),
                  ),
                  SizedBox(
                    width: 210,
                    child: drop<int?>('Maximum stops', maxStops, const {
                      null: 'Any · default',
                      0: 'Nonstop',
                      1: 'Maximum 1',
                      2: 'Maximum 2',
                    }, (v) => setState(() => maxStops = v)),
                  ),
                  SizedBox(
                    width: 220,
                    child: drop<int>(
                      'Minimum layover',
                      minLayover,
                      const {
                        45: '45 minutes',
                        60: '60 minutes · default',
                        90: '90 minutes',
                      },
                      (v) => setState(() => minLayover = v),
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: drop<int>(
                      'Maximum layover',
                      maxLayover,
                      const {
                        180: '3 hours',
                        300: '5 hours · default',
                        360: '6 hours',
                        480: '8 hours',
                      },
                      (v) => setState(() => maxLayover = v),
                    ),
                  ),
                  SizedBox(
                    width: 230,
                    child: drop<int?>(
                      'Max time/direction',
                      maxDuration,
                      const {
                        null: 'No maximum · default',
                        720: '12 hours',
                        1080: '18 hours',
                        1440: '24 hours',
                        2160: '36 hours',
                      },
                      (v) => setState(() => maxDuration = v),
                    ),
                  ),
                  FilterChip(
                    label: const Text('Avoid red-eyes · default'),
                    selected: avoidRedEye,
                    onSelected: (v) => setState(() => avoidRedEye = v),
                  ),
                ],
              ),
            ),
            _card(
              'Notifications',
              Icons.bedtime_outlined,
              Wrap(
                spacing: 14,
                runSpacing: 14,
                children: [
                  SizedBox(
                    width: 300,
                    child: TextField(
                      controller: timezone,
                      decoration: const InputDecoration(
                        labelText: 'IANA timezone',
                        hintText: 'America/New_York',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 190,
                    child: drop<int>(
                      'Quiet hours start',
                      quietStart,
                      {
                        for (var i = 0; i < 24; i++)
                          i: '${i.toString().padLeft(2, '0')}:00${i == 22 ? ' · default' : ''}',
                      },
                      (v) => setState(() => quietStart = v),
                    ),
                  ),
                  SizedBox(
                    width: 190,
                    child: drop<int>('Quiet hours end', quietEnd, {
                      for (var i = 0; i < 24; i++)
                        i: '${i.toString().padLeft(2, '0')}:00${i == 7 ? ' · default' : ''}',
                    }, (v) => setState(() => quietEnd = v)),
                  ),
                  const SizedBox(
                    width: 400,
                    child: Text(
                      'Nonurgent watch checks are deferred before consuming a call. Near-departure and near-target watches remain urgent.',
                    ),
                  ),
                ],
              ),
            ),
            FilledButton.icon(
              onPressed: loading || saving ? null : save,
              icon: const Icon(Icons.save_outlined),
              label: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Text(saving ? 'Saving…' : 'Save profile defaults'),
              ),
            ),
            const SizedBox(height: 18),
            _card(
              'App connection',
              Icons.security_outlined,
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Change the Railway URL or private app token. The token is stored using the platform secure-storage service.',
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: _connectionDialog,
                    icon: const Icon(Icons.key),
                    label: const Text('Change connection'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    ),
  );

  Widget _card(String title, IconData icon, Widget child) => Card(
    margin: const EdgeInsets.symmetric(vertical: 8),
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Text(
                title,
                style: Theme.of(
                  context,
                ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    ),
  );
  Widget _number(
    String label,
    int value,
    int min,
    int max,
    ValueChanged<int> changed,
  ) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8),
    decoration: BoxDecoration(
      border: Border.all(color: Colors.blueGrey.shade200),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('$label: ', style: const TextStyle(fontWeight: FontWeight.w600)),
        IconButton(
          onPressed: value > min ? () => changed(value - 1) : null,
          icon: const Icon(Icons.remove_circle_outline),
        ),
        Text('$value'),
        IconButton(
          onPressed: value < max ? () => changed(value + 1) : null,
          icon: const Icon(Icons.add_circle_outline),
        ),
      ],
    ),
  );
  Widget drop<T>(
    String label,
    T value,
    Map<T, String> choices,
    ValueChanged<T> changed,
  ) => DropdownButtonFormField<T>(
    initialValue: value,
    isExpanded: true,
    decoration: InputDecoration(labelText: label),
    items: choices.entries
        .map(
          (e) => DropdownMenuItem(
            value: e.key,
            child: Text(e.value, overflow: TextOverflow.ellipsis),
          ),
        )
        .toList(),
    onChanged: (v) {
      if (v != null || choices.containsKey(null)) changed(v as T);
    },
  );

  Future<void> _connectionDialog() async {
    final url = TextEditingController(text: widget.api.baseUrl),
        token = TextEditingController();
    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Change secure connection'),
        content: SizedBox(
          width: 520,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: url,
                decoration: const InputDecoration(
                  labelText: 'Railway HTTPS URL',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: token,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'APP_ACCESS_TOKEN',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (token.text.length < 16) return;
              await widget.onConfigure(url.text, token.text);
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }
}
