import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flight_companion/api_client.dart';
import 'package:flight_companion/main.dart';
import 'package:flight_companion/screens/search_screen.dart';
import 'package:flight_companion/screens/settings_screen.dart';

class _FakeApi extends FlightApi {
  _FakeApi() : super(baseUrl: 'https://example.test', token: 'test-token');

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async =>
      <String, dynamic>{};
}

void main() {
  testWidgets('shows secure connection setup', (tester) async {
    await tester.pumpWidget(
      MaterialApp(home: ConnectionSetup(onSave: (_, _) async {})),
    );
    expect(find.text('Connect Flight Companion'), findsOneWidget);
    expect(find.text('Save secure connection'), findsOneWidget);
  });

  testWidgets('desktop search fits without scrolling', (tester) async {
    tester.view.physicalSize = const Size(1179, 993);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SearchScreen(api: _FakeApi())),
      ),
    );

    final button = find.text('Review and search live fares');
    expect(button, findsOneWidget);
    expect(tester.getBottomLeft(button).dy, lessThan(993));
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('Comfort & price'));
    await tester.pumpAndSettle();
    expect(find.text('Price & airline preferences'), findsOneWidget);
    expect(find.text('Optimization & comfort'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('Search strategy'));
    await tester.pumpAndSettle();
    expect(find.text('Smart progressive · recommended'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('desktop settings fit without scrolling', (tester) async {
    tester.view.physicalSize = const Size(1179, 993);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SettingsScreen(api: _FakeApi(), onConfigure: (_, _) async {}),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final button = find.text('Change connection');
    expect(button, findsOneWidget);
    expect(tester.getBottomLeft(button).dy, lessThan(993));
    expect(tester.takeException(), isNull);
  });
}
