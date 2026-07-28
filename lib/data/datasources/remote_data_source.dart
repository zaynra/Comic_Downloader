import 'package:dio/dio.dart';

class RemoteDataSource {
  late final Dio _dio;
  String? _referer;

  RemoteDataSource({int maxWorkers = 6, String? referer}) {
    _referer = referer;
    _dio = Dio(BaseOptions(
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 14) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Mobile Safari/537.36',
      },
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      sendTimeout: const Duration(seconds: 15),
    ));
  }

  void setReferer(String referer) {
    _referer = referer;
  }

  Future<String> fetchHtml(String url) async {
    final response = await _dio.get(url);
    return response.data;
  }

  Future<List<int>> downloadBytes(String url) async {
    final response = await _dio.get<List<int>>(
      url,
      options: Options(responseType: ResponseType.bytes),
    );
    return response.data!;
  }

  Future<void> downloadToFile(String url, String filePath, {String? referer}) async {
    await _dio.download(
      url,
      filePath,
      options: Options(
        headers: {
          if (referer != null) 'Referer': referer,
          if (_referer != null && referer == null) 'Referer': _referer,
        },
      ),
    );
  }

  Future<List<bool>> downloadBatch(List<(String, String)> tasks) async {
    final results = <bool>[];
    for (final (url, path) in tasks) {
      try {
        await downloadToFile(url, path);
        results.add(true);
      } catch (_) {
        await Future.delayed(const Duration(milliseconds: 500));
        try {
          await downloadToFile(url, path);
          results.add(true);
        } catch (_) {
          results.add(false);
        }
      }
    }
    return results;
  }
}
