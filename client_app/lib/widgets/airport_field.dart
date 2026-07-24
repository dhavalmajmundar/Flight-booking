import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';

class AirportField extends StatefulWidget {
  const AirportField({
    super.key,
    required this.api,
    required this.controller,
    required this.labelText,
    required this.prefixIcon,
  });

  final FlightApi api;
  final TextEditingController controller;
  final String labelText;
  final IconData prefixIcon;

  @override
  State<AirportField> createState() => _AirportFieldState();
}

class _AirportFieldState extends State<AirportField> {
  static final Map<String, List<Map<String, dynamic>>> _cache = {};

  Timer? _debounce;
  List<Map<String, dynamic>> _suggestions = [];
  String? _resolvedLabel;
  String? _selectedCode;
  bool _loading = false;
  int _requestSequence = 0;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onTextChanged);
    if (widget.controller.text.trim().isNotEmpty) {
      _onTextChanged();
    }
  }

  @override
  void didUpdateWidget(covariant AirportField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller == widget.controller) return;
    oldWidget.controller.removeListener(_onTextChanged);
    widget.controller.addListener(_onTextChanged);
    _onTextChanged();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    widget.controller.removeListener(_onTextChanged);
    super.dispose();
  }

  void _onTextChanged() {
    final query = widget.controller.text.trim();
    _debounce?.cancel();
    if (_selectedCode != query.toUpperCase()) {
      _selectedCode = null;
      _resolvedLabel = null;
    }
    if (query.length < 2) {
      if (mounted) {
        setState(() {
          _loading = false;
          _suggestions = [];
        });
      }
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () => _lookup(query));
  }

  Future<void> _lookup(String query) async {
    final normalized = query.trim().toLowerCase();
    final sequence = ++_requestSequence;
    if (mounted) setState(() => _loading = true);
    try {
      final cached = _cache[normalized];
      final dynamic response =
          cached ?? await widget.api.get('/airports', {'q': query.trim()});
      final items = cached ?? _parse(response);
      _cache[normalized] = items;
      if (!mounted ||
          sequence != _requestSequence ||
          widget.controller.text.trim().toLowerCase() != normalized) {
        return;
      }
      final upper = query.trim().toUpperCase();
      final exact = items
          .where((item) => item['code'].toString().toUpperCase() == upper)
          .firstOrNull;
      setState(() {
        _loading = false;
        _resolvedLabel = exact?['label']?.toString();
        _selectedCode = exact == null ? null : upper;
        _suggestions = exact == null ? items.take(5).toList() : [];
      });
    } catch (_) {
      if (mounted && sequence == _requestSequence) {
        setState(() {
          _loading = false;
          _suggestions = [];
        });
      }
    }
  }

  List<Map<String, dynamic>> _parse(dynamic response) {
    if (response is! List) return [];
    return response
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .where(
          (item) =>
              item['code']?.toString().isNotEmpty == true &&
              item['label']?.toString().isNotEmpty == true,
        )
        .toList();
  }

  void _select(Map<String, dynamic> suggestion) {
    final code = suggestion['code'].toString().toUpperCase();
    setState(() {
      _selectedCode = code;
      _resolvedLabel = suggestion['label'].toString();
      _suggestions = [];
    });
    widget.controller.value = TextEditingValue(
      text: code,
      selection: TextSelection.collapsed(offset: code.length),
    );
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    mainAxisSize: MainAxisSize.min,
    children: [
      TextField(
        controller: widget.controller,
        textCapitalization: TextCapitalization.characters,
        decoration: InputDecoration(
          labelText: widget.labelText,
          hintText: 'City, state, airport, or IATA code',
          prefixIcon: Icon(widget.prefixIcon),
          suffixIcon: _loading
              ? const Padding(
                  padding: EdgeInsets.all(14),
                  child: SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                )
              : null,
        ),
      ),
      if (_resolvedLabel != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.check_circle_outline,
                size: 17,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _resolvedLabel!,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ],
          ),
        ),
      if (_suggestions.isNotEmpty)
        Card(
          margin: const EdgeInsets.only(top: 4),
          elevation: 3,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 230),
            child: ListView.separated(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              itemCount: _suggestions.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final suggestion = _suggestions[index];
                return ListTile(
                  dense: true,
                  leading: const Icon(Icons.local_airport, size: 20),
                  title: Text(suggestion['label'].toString()),
                  onTap: () => _select(suggestion),
                );
              },
            ),
          ),
        ),
    ],
  );
}
