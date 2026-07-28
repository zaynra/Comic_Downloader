import 'package:webview_flutter/webview_flutter.dart';
import '../../domain/models/chapter.dart';
import '../../domain/models/series.dart';
import '../../domain/repositories/site_adapter.dart';

class JsFallbackAdapter implements BaseSiteAdapter {
  final String baseUrl;
  final bool enabled;

  const JsFallbackAdapter({
    required this.baseUrl,
    this.enabled = true,
  });

  @override
  String get name => 'JS Fallback ($baseUrl)';

  @override
  Future<List<Series>> search(String query) async {
    return [];
  }

  @override
  Future<String> getTitle(String seriesUrl) async {
    final result = await _evaluateJs(seriesUrl, '''
      document.title || 
      document.querySelector('h1')?.innerText || 
      document.querySelector('title')?.innerText || ''
    ''');
    return result ?? 'Unknown';
  }

  @override
  Future<List<Chapter>> getChapters(String seriesUrl) async {
    final result = await _evaluateJs(seriesUrl, '''
      const links = document.querySelectorAll('a[href*="chapter"], a[href*="ch"], a[href*="episode"]');
      JSON.stringify(Array.from(links).map(a => ({
        url: a.href,
        text: a.innerText.trim()
      })));
    ''');
    if (result == null) return [];

    try {
      final parsed = _parseChapterList(result);
      return parsed;
    } catch (_) {
      return [];
    }
  }

  @override
  double getChapterNumber(String chapUrl) {
    final regex = RegExp(r'(\d+(?:\.\d+)?)');
    final match = regex.firstMatch(chapUrl);
    if (match != null) return double.parse(match.group(1)!);
    final pathParts = chapUrl.split('/');
    for (final part in pathParts.reversed) {
      final m = regex.firstMatch(part);
      if (m != null) return double.parse(m.group(1)!);
    }
    return 0;
  }

  @override
  Future<List<String>> getChapterImages(String chapUrl, {bool Function()? isCancelled}) async {
    final result = await _evaluateJs(chapUrl, '''
      const imgs = document.querySelectorAll('img[src*="comic"], img[src*="chapter"], img[src*="scan"], img[src*="page"]');
      JSON.stringify(Array.from(imgs).map(img => img.src || img.getAttribute('data-src') || ''));
    ''');
    if (result == null) return [];

    try {
      final parsed = _parseImageList(result);
      return parsed.where((url) => url.isNotEmpty).toList();
    } catch (_) {
      return [];
    }
  }

  Future<String?> _evaluateJs(String url, String js) async {
    try {
      final controller = WebViewController()
        ..setJavaScriptMode(JavaScriptMode.unrestricted)
        ..loadRequest(Uri.parse(url));

      await Future.delayed(const Duration(seconds: 3));
      final result = await controller.runJavaScriptReturningResult(js);
      return result.toString();
    } catch (_) {
      return null;
    }
  }

  List<Chapter> _parseChapterList(String json) {
    final chapters = <Chapter>[];
    try {
      final list = _parseJsonArray(json);
      for (final item in list) {
        final url = item['url'] as String? ?? '';
        final text = item['text'] as String? ?? '';
        final num = getChapterNumber(url);
        chapters.add(Chapter(
          number: num,
          url: url,
          label: text.isNotEmpty ? text : num.toString(),
        ));
      }
    } catch (_) {}
    return chapters;
  }

  List<String> _parseImageList(String json) {
    try {
      return _parseJsonStringArray(json);
    } catch (_) {
      return [];
    }
  }

  List<Map<String, dynamic>> _parseJsonArray(String json) {
    final decoded = _parseJson(json);
    if (decoded is List) {
      return decoded.cast<Map<String, dynamic>>();
    }
    return [];
  }

  List<String> _parseJsonStringArray(String json) {
    final decoded = _parseJson(json);
    if (decoded is List) {
      return decoded.cast<String>();
    }
    return [];
  }

  dynamic _parseJson(String json) {
    try {
      return _simpleJsonParse(json);
    } catch (_) {
      return null;
    }
  }

  dynamic _simpleJsonParse(String json) {
    json = json.trim();
    if (json.startsWith('[') && json.endsWith(']')) {
      final inner = json.substring(1, json.length - 1);
      if (inner.trim().isEmpty) return [];

      final items = <dynamic>[];
      int depth = 0;
      bool inString = false;
      bool escape = false;
      final buffer = StringBuffer();

      for (int i = 0; i < inner.length; i++) {
        final char = inner[i];
        if (escape) {
          buffer.write(char);
          escape = false;
          continue;
        }
        if (char == '\\') { escape = true; buffer.write(char); continue; }
        if (char == '"' && !inString) { inString = true; buffer.write(char); continue; }
        if (char == '"' && inString) { inString = false; buffer.write(char); continue; }
        if (!inString) {
          if (char == '{' || char == '[') depth++;
          if (char == '}' || char == ']') depth--;
          if (char == ',' && depth == 0) {
            items.add(_parseJsonValue(buffer.toString().trim()));
            buffer.clear();
            continue;
          }
        }
        buffer.write(char);
      }
      final last = buffer.toString().trim();
      if (last.isNotEmpty) items.add(_parseJsonValue(last));

      return items;
    }
    return null;
  }

  dynamic _parseJsonValue(String val) {
    if (val.startsWith('{')) return _parseJsonObject(val);
    if (val.startsWith('[')) return _simpleJsonParse(val);
    if (val.startsWith('"')) return val.substring(1, val.length - 1);
    if (val == 'null') return null;
    if (val == 'true' || val == 'false') return val == 'true';
    return num.tryParse(val) ?? val;
  }

  Map<String, dynamic> _parseJsonObject(String json) {
    final map = <String, dynamic>{};
    json = json.substring(1, json.length - 1).trim();
    if (json.isEmpty) return map;

    int depth = 0;
    bool inString = false;
    bool escape = false;
    bool inKey = true;
    final keyBuffer = StringBuffer();
    final valueBuffer = StringBuffer();
    String? currentKey;

    for (int i = 0; i < json.length; i++) {
      final char = json[i];
      if (escape) {
        (inKey ? keyBuffer : valueBuffer).write(char);
        escape = false;
        continue;
      }
      if (char == '\\') { escape = true; continue; }
      if (char == '"') {
        inString = !inString;
        (inKey ? keyBuffer : valueBuffer).write(char);
        continue;
      }
      if (!inString) {
        if (char == '{' || char == '[') depth++;
        if (char == '}' || char == ']') depth--;
        if (char == ':' && depth == 0 && inKey) {
          currentKey = keyBuffer.toString().trim();
          currentKey = currentKey.substring(1, currentKey.length - 1);
          keyBuffer.clear();
          inKey = false;
          continue;
        }
        if ((char == ',' || char == '}') && depth == 0 && !inKey) {
          final val = _parseJsonValue(valueBuffer.toString().trim());
          if (currentKey != null) map[currentKey] = val;
          valueBuffer.clear();
          inKey = true;
          currentKey = null;
          if (char == '}') break;
          continue;
        }
      }
      (inKey ? keyBuffer : valueBuffer).write(char);
    }

    if (!inKey && currentKey != null) {
      map[currentKey] = _parseJsonValue(valueBuffer.toString().trim());
    }

    return map;
  }
}
