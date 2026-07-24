import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api_client.dart';
import '../widgets/airport_field.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key, required this.api});
  final FlightApi api;
  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final origin = TextEditingController();
  final destination = TextEditingController();
  final preferred = TextEditingController();
  final avoided = TextEditingController();
  final requiredAirlines = TextEditingController();
  final budget = TextEditingController();
  DateTime departure = DateTime.now().add(const Duration(days: 30));
  DateTime? returning = DateTime.now().add(const Duration(days: 37));
  int adults = 4, flexibleDays = 3, checkedBags = 2, carryOn = 1;
  int minLayover = 60, maxLayover = 300;
  int? maxStops, maxDuration;
  String cabin = 'ECONOMY', nearby = 'auto', priority = 'balanced';
  String currency = 'USD', departureWindow = 'any', strategy = 'progressive';
  bool flexible = true,
      smartBaggage = false,
      avoidRedEye = true,
      loading = false;
  Map<String, dynamic>? results;

  String _date(DateTime value) => value.toIso8601String().split('T').first;
  List<String> _codes(String value) => value
      .split(',')
      .map((e) => e.trim().toUpperCase())
      .where((e) => e.isNotEmpty)
      .toList();

  Map<String, dynamic> get payload => {
    'origin': origin.text.trim(),
    'destination': destination.text.trim(),
    'departure_date': _date(departure),
    'return_date': returning == null ? null : _date(returning!),
    'adults': adults,
    'cabin': cabin,
    'flexible_dates': flexible,
    'flexible_days': flexibleDays,
    'nearby_mode': nearby,
    'checked_bags': checkedBags,
    'carry_on_bags': carryOn,
    'smart_baggage': smartBaggage,
    'preferred_airlines': _codes(preferred.text),
    'avoided_airlines': _codes(avoided.text),
    'required_airlines': _codes(requiredAirlines.text),
    'max_budget': double.tryParse(budget.text.replaceAll(',', '')),
    'priority': priority,
    'currency': currency,
    'departure_window': departureWindow,
    'avoid_red_eye': avoidRedEye,
    'max_stops': maxStops,
    'min_layover_minutes': minLayover,
    'max_layover_minutes': maxLayover,
    'max_total_duration_minutes': maxDuration,
    'search_mode': strategy,
  };

  int get maximumCalls {
    if (strategy == 'exact') return 1;
    if (strategy == 'suggested') return 1 + (nearby == 'no' ? 0 : 4);
    final dates = flexible ? flexibleDays * 2 + 1 : 1;
    return dates + (nearby == 'no' ? 0 : 4);
  }

  Future<void> _pickDate(bool isReturn) async {
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 730)),
      initialDate: isReturn
          ? (returning ?? departure.add(const Duration(days: 7)))
          : departure,
    );
    if (picked == null) return;
    setState(() {
      if (isReturn) {
        returning = picked;
      } else {
        final duration =
            returning?.difference(departure) ?? const Duration(days: 7);
        departure = picked;
        if (returning != null) returning = picked.add(duration);
      }
    });
  }

  Future<void> _search() async {
    if (origin.text.trim().length < 2 || destination.text.trim().length < 2) {
      _message('Enter both origin and destination.');
      return;
    }
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirm live search'),
        content: Text(
          '${origin.text} → ${destination.text}\n${_date(departure)}${returning == null ? ' · one-way' : ' → ${_date(returning!)}'}\n$adults adult(s) · ${cabin.replaceAll('_', ' ')} · $priority\n\nMaximum disclosed RouteStack search calls: $maximumCalls\nNo payment or booking occurs.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Search live fares'),
          ),
        ],
      ),
    );
    if (approved != true) return;
    setState(() {
      loading = true;
      results = null;
    });
    try {
      final value = await widget.api.post('/search', payload);
      if (mounted) setState(() => results = Map<String, dynamic>.from(value));
    } catch (error) {
      _message(error.toString());
    }
    if (mounted) setState(() => loading = false);
  }

  void _message(String text) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.all(20),
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1100),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Find the right flight',
              style: Theme.of(
                context,
              ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
            ),
            const Text(
              'Every preference is adjustable. Unsafe or mismatched itineraries remain visible with clear warnings.',
            ),
            const SizedBox(height: 18),
            _Section(
              title: 'Route & dates',
              icon: Icons.route_outlined,
              child: Column(
                children: [
                  LayoutBuilder(
                    builder: (context, size) {
                      final fromField = AirportField(
                        api: widget.api,
                        controller: origin,
                        labelText: 'From city or airport',
                        prefixIcon: Icons.flight_takeoff,
                      );
                      final toField = AirportField(
                        api: widget.api,
                        controller: destination,
                        labelText: 'To city or airport',
                        prefixIcon: Icons.flight_land,
                      );
                      final swap = IconButton(
                        onPressed: () {
                          final temp = origin.text;
                          origin.text = destination.text;
                          destination.text = temp;
                        },
                        icon: const Icon(Icons.swap_horiz_rounded),
                        tooltip: 'Swap route',
                      );
                      if (size.maxWidth > 650) {
                        return Row(
                          children: [
                            Expanded(child: fromField),
                            const SizedBox(width: 12),
                            swap,
                            const SizedBox(width: 12),
                            Expanded(child: toField),
                          ],
                        );
                      }
                      return Column(
                        children: [
                          fromField,
                          const SizedBox(height: 6),
                          swap,
                          const SizedBox(height: 6),
                          toField,
                        ],
                      );
                    },
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      OutlinedButton.icon(
                        onPressed: () => _pickDate(false),
                        icon: const Icon(Icons.calendar_month),
                        label: Text('Depart ${_date(departure)}'),
                      ),
                      OutlinedButton.icon(
                        onPressed: returning == null
                            ? null
                            : () => _pickDate(true),
                        icon: const Icon(Icons.event_repeat),
                        label: Text(
                          returning == null
                              ? 'One-way'
                              : 'Return ${_date(returning!)}',
                        ),
                      ),
                      SegmentedButton<bool>(
                        segments: const [
                          ButtonSegment(value: false, label: Text('One-way')),
                          ButtonSegment(value: true, label: Text('Round trip')),
                        ],
                        selected: {returning != null},
                        onSelectionChanged: (value) => setState(
                          () => returning = value.first
                              ? departure.add(const Duration(days: 7))
                              : null,
                        ),
                      ),
                    ],
                  ),
                  if (returning != null) ...[
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      children: [3, 5, 7, 10, 14, 21, 30]
                          .map(
                            (days) => ChoiceChip(
                              label: Text(
                                '$days days${days == 7 ? ' · default' : ''}',
                              ),
                              selected:
                                  returning!.difference(departure).inDays ==
                                  days,
                              onSelected: (_) => setState(
                                () => returning = departure.add(
                                  Duration(days: days),
                                ),
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  ],
                ],
              ),
            ),
            _ResponsiveSectionGrid(
              children: [
                _Section(
                  title: 'Travelers & cabin',
                  icon: Icons.people_outline,
                  child: Wrap(
                    spacing: 14,
                    runSpacing: 14,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      _Stepper(
                        label: 'Adults',
                        value: adults,
                        minimum: 1,
                        maximum: 9,
                        onChanged: (v) => setState(() => adults = v),
                      ),
                      SizedBox(
                        width: 260,
                        child: _dropdown('Cabin', cabin, const {
                          'ECONOMY': 'Economy · default',
                          'PREMIUM_ECONOMY': 'Premium economy',
                          'BUSINESS': 'Business',
                          'FIRST': 'First',
                        }, (v) => setState(() => cabin = v)),
                      ),
                      SizedBox(
                        width: 190,
                        child: _dropdown('Currency', currency, const {
                          'USD': 'USD · default',
                          'CAD': 'CAD',
                          'EUR': 'EUR',
                          'GBP': 'GBP',
                          'INR': 'INR',
                        }, (v) => setState(() => currency = v)),
                      ),
                    ],
                  ),
                ),
                _Section(
                  title: 'Dates & nearby airports',
                  icon: Icons.date_range_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Flexible dates'),
                        subtitle: const Text(
                          'Yes is selected by default and can reveal cheaper travel days.',
                        ),
                        value: flexible,
                        onChanged: (v) => setState(() => flexible = v),
                      ),
                      if (flexible)
                        Wrap(
                          spacing: 8,
                          children: [1, 2, 3, 5, 7]
                              .map(
                                (days) => ChoiceChip(
                                  label: Text(
                                    '±$days day${days == 1 ? '' : 's'}${days == 3 ? ' · default' : ''}',
                                  ),
                                  selected: flexibleDays == days,
                                  onSelected: (_) =>
                                      setState(() => flexibleDays = days),
                                ),
                              )
                              .toList(),
                        ),
                      const SizedBox(height: 14),
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 350),
                        child: _dropdown('Nearby airports', nearby, const {
                          'auto':
                              'Auto: domestic on, international off · default',
                          'yes': 'Always include',
                          'no': 'Never include',
                        }, (v) => setState(() => nearby = v)),
                      ),
                    ],
                  ),
                ),
                _Section(
                  title: 'Baggage',
                  icon: Icons.luggage_outlined,
                  child: Wrap(
                    spacing: 18,
                    runSpacing: 12,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      _Stepper(
                        label: 'Checked bags',
                        value: checkedBags,
                        minimum: 0,
                        maximum: 2,
                        onChanged: smartBaggage
                            ? null
                            : (v) => setState(() => checkedBags = v),
                      ),
                      _Stepper(
                        label: 'Carry-ons',
                        value: carryOn,
                        minimum: 0,
                        maximum: 2,
                        onChanged: (v) => setState(() => carryOn = v),
                      ),
                      FilterChip(
                        label: const Text(
                          'Smart bags: 0 domestic / 2 international',
                        ),
                        selected: smartBaggage,
                        onSelected: (v) => setState(() => smartBaggage = v),
                      ),
                    ],
                  ),
                ),
                _Section(
                  title: 'Price & airline preferences',
                  icon: Icons.payments_outlined,
                  child: Wrap(
                    spacing: 14,
                    runSpacing: 14,
                    children: [
                      SizedBox(
                        width: 250,
                        child: TextField(
                          controller: budget,
                          keyboardType: TextInputType.number,
                          decoration: InputDecoration(
                            labelText: 'Maximum total budget ($currency)',
                            hintText: 'No maximum · default',
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 250,
                        child: TextField(
                          controller: requiredAirlines,
                          decoration: const InputDecoration(
                            labelText: 'Only these airlines',
                            hintText: 'DL, UA · optional',
                            helperText: 'Show trips containing any listed code',
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 250,
                        child: TextField(
                          controller: preferred,
                          decoration: const InputDecoration(
                            labelText: 'Preferred airlines',
                            hintText: 'DL, UA',
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 250,
                        child: TextField(
                          controller: avoided,
                          decoration: const InputDecoration(
                            labelText: 'Airlines to avoid',
                            hintText: 'NK, F9',
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                _Section(
                  title: 'Optimization & comfort',
                  icon: Icons.tune_rounded,
                  child: Wrap(
                    spacing: 14,
                    runSpacing: 14,
                    children: [
                      SizedBox(
                        width: 230,
                        child: _dropdown(
                          'Sort priority',
                          priority,
                          const {
                            'cheapest': 'Cheapest',
                            'balanced': 'Balanced · default',
                            'fastest': 'Fastest',
                            'nonstop': 'Nonstop',
                          },
                          (v) => setState(() => priority = v),
                        ),
                      ),
                      SizedBox(
                        width: 230,
                        child: _dropdown(
                          'Outbound departure',
                          departureWindow,
                          const {
                            'any': 'Any time · default',
                            'morning': 'Morning 5–12',
                            'afternoon': 'Afternoon 12–17',
                            'evening': 'Evening 17–22',
                          },
                          (v) => setState(() => departureWindow = v),
                        ),
                      ),
                      SizedBox(
                        width: 210,
                        child: _dropdown<int?>(
                          'Maximum stops',
                          maxStops,
                          const {
                            null: 'Any · default',
                            0: 'Nonstop',
                            1: 'Maximum 1',
                            2: 'Maximum 2',
                          },
                          (v) => setState(() => maxStops = v),
                        ),
                      ),
                      SizedBox(
                        width: 220,
                        child: _dropdown<int?>(
                          'Travel time / direction',
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
                      SizedBox(
                        width: 240,
                        child: _dropdown<int>(
                          'Minimum connection',
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
                        width: 240,
                        child: _dropdown<int>(
                          'Maximum connection',
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
                      FilterChip(
                        label: const Text('Avoid red-eyes · default'),
                        selected: avoidRedEye,
                        onSelected: (v) => setState(() => avoidRedEye = v),
                      ),
                    ],
                  ),
                ),
                _Section(
                  title: 'Search strategy',
                  icon: Icons.speed_rounded,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 430,
                        child: _dropdown('Strategy', strategy, const {
                          'progressive': 'Smart progressive · recommended',
                          'suggested': 'Suggested date only',
                          'full': 'Full flexible-date comparison',
                          'exact': 'Exact date only',
                        }, (v) => setState(() => strategy = v)),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Maximum disclosed usage: $maximumCalls RouteStack search call(s). Progressive mode stops early when it finds usable results.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            FilledButton.icon(
              onPressed: loading ? null : _search,
              icon: const Icon(Icons.search),
              label: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Text(
                  loading ? 'Searching…' : 'Review and search live fares',
                ),
              ),
            ),
            if (loading)
              const Padding(
                padding: EdgeInsets.all(18),
                child: LinearProgressIndicator(),
              ),
            if (results != null) ResultsPanel(api: widget.api, data: results!),
            const SizedBox(height: 40),
          ],
        ),
      ),
    ),
  );

  Widget _dropdown<T>(
    String label,
    T value,
    Map<T, String> choices,
    ValueChanged<T> changed,
  ) => DropdownButtonFormField<T>(
    initialValue: value,
    decoration: InputDecoration(labelText: label),
    isExpanded: true,
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
}

class ResultsPanel extends StatelessWidget {
  const ResultsPanel({super.key, required this.api, required this.data});
  final FlightApi api;
  final Map<String, dynamic> data;
  @override
  Widget build(BuildContext context) {
    final options = List<Map<String, dynamic>>.from(
      (data['options'] as List? ?? []).map((e) => Map<String, dynamic>.from(e)),
    );
    final dates = List<Map<String, dynamic>>.from(
      (data['lowest_by_date'] as List? ?? []).map(
        (e) => Map<String, dynamic>.from(e),
      ),
    );
    final lowestDatePrice = dates.isEmpty
        ? 0.0
        : dates
              .map((item) => (item['price'] as num).toDouble())
              .reduce((a, b) => a < b ? a : b);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 24),
        Text(
          '${data['origin_label'] ?? ''} → ${data['destination_label'] ?? ''}',
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
        ),
        Text(data['search_note']?.toString() ?? ''),
        if (dates.isNotEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Flexible-date price calendar',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: dates.map((item) {
                      final ratio =
                          (item['price'] as num).toDouble() / lowestDatePrice;
                      return Chip(
                        backgroundColor: ratio <= 1.05
                            ? Colors.green.shade50
                            : ratio <= 1.15
                            ? Colors.amber.shade50
                            : Colors.red.shade50,
                        avatar: Icon(
                          ratio <= 1.05
                              ? Icons.trending_down
                              : ratio <= 1.15
                              ? Icons.remove
                              : Icons.trending_up,
                          size: 18,
                        ),
                        label: Text(
                          '${item['date']}\n${item['currency']} ${_money(item['price'])}',
                        ),
                      );
                    }).toList(),
                  ),
                ],
              ),
            ),
          ),
        if (options.isEmpty)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'No matching live offers were returned. Try a wider date range, nearby airports, or fewer restrictions.',
              ),
            ),
          ),
        ...options.asMap().entries.map(
          (entry) => _FlightCard(
            api: api,
            option: entry.value,
            checkoutToken: data['checkout_token']?.toString(),
            index: entry.key,
          ),
        ),
      ],
    );
  }

  static String _money(dynamic value) =>
      (value as num?)?.toStringAsFixed(2) ?? '—';
}

class _FlightCard extends StatelessWidget {
  const _FlightCard({
    required this.api,
    required this.option,
    required this.checkoutToken,
    required this.index,
  });
  final FlightApi api;
  final Map<String, dynamic> option;
  final String? checkoutToken;
  final int index;
  String duration(int minutes) =>
      '${minutes ~/ 60}h ${(minutes % 60).toString().padLeft(2, '0')}m';
  @override
  Widget build(BuildContext context) {
    final warnings = List<String>.from(option['warnings'] ?? []);
    final tags = List<String>.from(option['tags'] ?? []);
    final legs = List<Map<String, dynamic>>.from(
      (option['legs'] as List).map((e) => Map<String, dynamic>.from(e)),
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(child: Text('#${option['rank']}')),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    (option['airlines'] as List).join(', '),
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                Text(
                  '${option['currency']} ${(option['total_price'] as num).toStringAsFixed(2)}',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
              ],
            ),
            if (tags.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(
                  spacing: 6,
                  children: tags
                      .map(
                        (tag) => Chip(
                          label: Text(tag),
                          visualDensity: VisualDensity.compact,
                        ),
                      )
                      .toList(),
                ),
              ),
            Text(
              '${option['currency']} ${(option['per_traveler'] as num).toStringAsFixed(2)} per traveler · ${duration(option['duration_minutes'])} · ${option['stops'] == 0 ? 'Nonstop' : '${option['stops']} stop(s)'}',
            ),
            if ((option['price_delta'] as num?) != null &&
                (option['price_delta'] as num) > 0)
              Text(
                '${option['currency']} ${(option['price_delta'] as num).toStringAsFixed(2)} more than cheapest'
                '${option['cost_per_hour_saved'] == null ? '' : ' · ${option['currency']} ${(option['cost_per_hour_saved'] as num).toStringAsFixed(2)} per hour saved'}',
              ),
            const Divider(height: 24),
            ...legs.map(
              (leg) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.flight),
                title: Text('${leg['origin']} → ${leg['destination']}'),
                subtitle: Text(
                  '${leg['departure']}\n${leg['arrival']} · ${duration(leg['duration_minutes'])}',
                ),
              ),
            ),
            Text(
              'Baggage: ${option['checked_bags'] ?? 'unreported'} checked · ${option['carry_on_bags'] ?? 'unreported'} carry-on',
            ),
            if (warnings.isNotEmpty)
              Container(
                margin: const EdgeInsets.only(top: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: warnings.any((e) => e.startsWith('HIGH RISK'))
                      ? Colors.red.shade50
                      : Colors.amber.shade50,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  warnings.join('\n'),
                  style: TextStyle(
                    color: warnings.any((e) => e.startsWith('HIGH RISK'))
                        ? Colors.red.shade900
                        : Colors.amber.shade900,
                  ),
                ),
              ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: checkoutToken == null
                      ? null
                      : () async {
                          try {
                            final result = await api.post(
                              '/checkout/$checkoutToken/$index',
                            );
                            await launchUrl(
                              Uri.parse(result['url']),
                              mode: LaunchMode.externalApplication,
                            );
                          } catch (e) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())),
                              );
                            }
                          }
                        },
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('Revalidate exact fare'),
                ),
                ...Map<String, dynamic>.from(option['links']).entries.map(
                  (e) => OutlinedButton(
                    onPressed: () => launchUrl(
                      Uri.parse(e.value),
                      mode: LaunchMode.externalApplication,
                    ),
                    child: Text(e.key.replaceAll('_', ' ')),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.title,
    required this.icon,
    required this.child,
  });
  final String title;
  final IconData icon;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final heading = Text(
      title,
      style: Theme.of(
        context,
      ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
    );
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 5),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: Theme.of(context).colorScheme.primary),
                const SizedBox(width: 9),
                Expanded(child: heading),
              ],
            ),
            const SizedBox(height: 10),
            child,
          ],
        ),
      ),
    );
  }
}

class _ResponsiveSectionGrid extends StatelessWidget {
  const _ResponsiveSectionGrid({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      if (constraints.maxWidth < 900) {
        return Column(children: children);
      }

      Widget scrollable(Widget child) => SingleChildScrollView(child: child);
      return DefaultTabController(
        length: 3,
        child: SizedBox(
          height: 420,
          child: Column(
            children: [
              const TabBar(
                tabs: [
                  Tab(icon: Icon(Icons.tune), text: 'Trip preferences'),
                  Tab(
                    icon: Icon(Icons.airline_seat_recline_extra),
                    text: 'Comfort & price',
                  ),
                  Tab(icon: Icon(Icons.speed), text: 'Search strategy'),
                ],
              ),
              Expanded(
                child: TabBarView(
                  children: [
                    scrollable(
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(child: children[0]),
                          const SizedBox(width: 8),
                          Expanded(child: children[1]),
                          const SizedBox(width: 8),
                          Expanded(child: children[2]),
                        ],
                      ),
                    ),
                    scrollable(Column(children: [children[3], children[4]])),
                    scrollable(children[5]),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}

class _Stepper extends StatelessWidget {
  const _Stepper({
    required this.label,
    required this.value,
    required this.minimum,
    required this.maximum,
    required this.onChanged,
  });
  final String label;
  final int value, minimum, maximum;
  final ValueChanged<int>? onChanged;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      border: Border.all(color: const Color(0xFFCBD5E1)),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('$label: ', style: const TextStyle(fontWeight: FontWeight.w600)),
        IconButton(
          onPressed: onChanged != null && value > minimum
              ? () => onChanged!(value - 1)
              : null,
          icon: const Icon(Icons.remove_circle_outline),
        ),
        Text('$value', style: Theme.of(context).textTheme.titleMedium),
        IconButton(
          onPressed: onChanged != null && value < maximum
              ? () => onChanged!(value + 1)
              : null,
          icon: const Icon(Icons.add_circle_outline),
        ),
      ],
    ),
  );
}
