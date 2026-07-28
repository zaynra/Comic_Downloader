import 'dart:convert';
import 'dart:io';
import 'package:path/path.dart' as p;
class MetadataHelper {
  static Future<void> saveMetadataJson({
    required String seriesDir,
    required String title,
    required String url,
    String? author,
    String? genre,
    int? chapterCount,
    required String adapterName,
  }) async {
    final metadata = {
      'schema_version': 5,
      'format': 'Comic_Viewer Metadata',
      'source': 'Comic_Downloader Mobile',
      'title': title,
      'url': url,
      'author': author ?? '',
      'genre': genre ?? '',
      'total_chapters': chapterCount ?? 0,
      'adapter': adapterName,
      'created_at': DateTime.now().toIso8601String(),
    };

    final file = File(p.join(seriesDir, 'metadata.json'));
    await file.writeAsString(jsonEncode(metadata));
  }

  static Future<void> saveChapterJson({
    required String seriesDir,
    required double chapterNumber,
    required String chapterLabel,
    required String pdfPath,
    required int pageCount,
  }) async {
    final chapterMeta = {
      'chapter': chapterNumber,
      'label': chapterLabel,
      'pdf': p.basename(pdfPath),
      'pages': pageCount,
      'downloaded_at': DateTime.now().toIso8601String(),
    };

    final filename = '${formatPdfPrefix(chapterLabel)}.json';
    final file = File(p.join(seriesDir, filename));
    await file.writeAsString(jsonEncode(chapterMeta));
  }

  static String formatPdfPrefix(String chapterLabel) {
    return 'Chapter_$chapterLabel';
  }
}
