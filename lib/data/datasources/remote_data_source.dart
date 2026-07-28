import 'package:dio/dio.dart';

class RemoteDataSource {
  late final Dio _dio;

  RemoteDataSource({int maxWorkers = 6}) {
    _dio = Dio(BaseOptions(
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 14) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Mobile Safari/537.36',
      },
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
    ));
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

  Future<bool> downloadToFile(String url, String filePath) async {
    try {
      await _dio.download(url, filePath);
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<List<bool>> downloadBatch(List<(String, String)> tasks) async {
    final results = <bool>[];
    for (final (url, path) in tasks) {
      final ok = await downloadToFile(url, path);
      results.add(ok);
      if (!ok) {
        await Future.delayed(const Duration(milliseconds: 500));
        final retryOk = await downloadToFile(url, path);
        results[results.length - 1] = retryOk;
      }
    }
    return results;
  }
}
