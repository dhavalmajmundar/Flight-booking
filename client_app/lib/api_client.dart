import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message, [this.statusCode]);
  final String message;
  final int? statusCode;
  @override
  String toString() => message;
}

class FlightApi {
  FlightApi({required this.baseUrl, required this.token});
  final String baseUrl;
  final String token;

  Uri _uri(String path, [Map<String, String>? query]) => Uri.parse(
    '${baseUrl.replaceAll(RegExp(r'/+$'), '')}/api/v1$path',
  ).replace(queryParameters: query);

  Map<String, String> get _headers => {
    'Authorization': 'Bearer $token',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };

  Future<dynamic> get(String path, [Map<String, String>? query]) async =>
      _decode(await http.get(_uri(path, query), headers: _headers));

  Future<dynamic> post(String path, [Object? body]) async => _decode(
    await http.post(
      _uri(path),
      headers: _headers,
      body: jsonEncode(body ?? {}),
    ),
  );

  Future<dynamic> put(String path, Object body) async => _decode(
    await http.put(_uri(path), headers: _headers, body: jsonEncode(body)),
  );

  Future<dynamic> delete(String path) async =>
      _decode(await http.delete(_uri(path), headers: _headers));

  dynamic _decode(http.Response response) {
    dynamic data;
    try {
      data = response.body.isEmpty
          ? <String, dynamic>{}
          : jsonDecode(response.body);
    } catch (_) {
      throw ApiException(
        'The server returned an unreadable response.',
        response.statusCode,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = data is Map ? data['detail'] : null;
      throw ApiException(
        detail?.toString() ?? 'Request failed (${response.statusCode}).',
        response.statusCode,
      );
    }
    return data;
  }
}
