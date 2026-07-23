import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flight_companion/main.dart';

void main() {
  testWidgets('shows secure connection setup', (tester) async {
    await tester.pumpWidget(
      MaterialApp(home: ConnectionSetup(onSave: (_, _) async {})),
    );
    expect(find.text('Connect Flight Companion'), findsOneWidget);
    expect(find.text('Save secure connection'), findsOneWidget);
  });
}
