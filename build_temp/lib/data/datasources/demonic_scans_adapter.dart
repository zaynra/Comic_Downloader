import 'package:html/parser.dart' as parser;
import '../../domain/repositories/site_adapter.dart';
import '../../domain/models/series.dart';
import '../../domain/models/chapter.dart';
import 'remote_data_source.dart';

class DemonicScansAdapter implements BaseSiteAdapter {
  final RemoteDataSource _dataSource;

  @override
  final String name = 'demonicscans.org';

  static const _baseUrl = 'https://demonicscans.org';

  DemonicScansAdapter({RemoteDataSource? dataSource})
      : _dataSource = dataSource ?? RemoteDataSource();

  @override
  Future<List<Series>> search(String query) async {
    final html = await _dataSource.fetchHtml(
      '$_baseUrl/?s=$query',
    );
    final document = parser.parse(html);
    final results = <Series>[];

    for (final article in document.querySelectorAll('article, .post-item, .bs')) {
      final link = article.querySelector('a[href]');
      final img = article.querySelector('img');
      final titleEl = article.querySelector('h3, h2, .title');

      if (link == null) continue;
      final url = link.attributes['href'] ?? '';
      final title = titleEl?.text.trim() ?? link.attributes['title'] ?? '';
      final thumb = img?.attributes['src'] ?? img?.attributes['data-src'];

      if (title.isNotEmpty) {
        results.add(Series(
          id: Uri.tryParse(url)?.pathSegments.last ?? url,
          title: title,
          url: url,
          thumbnailUrl: thumb,
          adapterName: name,
        ));
      }
    }

    return results;
  }

  @override
  Future<String> getTitle(String seriesUrl) async {
    final html = await _dataSource.fetchHtml(seriesUrl);
    final document = parser.parse(html);

    final candidates = [
      document.querySelector('h1'),
      document.querySelector('meta[property="og:title"]'),
      document.querySelector('.series-title'),
    ];

    for (final tag in candidates) {
      if (tag == null) continue;
      final text = tag.attributes['content'] ?? tag.text.trim();
      if (text.length > 3 && !text.contains('BETA')) {
        return text.replaceAll(RegExp(r'[<>:"/\\|?*]'), '').trim();
      }
    }

    final slug = Uri.tryParse(seriesUrl)?.pathSegments.last ?? 'Unknown';
    return Uri.decodeComponent(slug);
  }

  @override
  Future<List<Chapter>> getChapters(String seriesUrl) async {
    final html = await _dataSource.fetchHtml(seriesUrl);
    final document = parser.parse(html);
    final links = <String>{};

    for (final a in document.querySelectorAll('a[href].chplinks')) {
      final href = a.attributes['href'] ?? '';
      if (href.contains('chaptered.php') && href.contains('&chapter=')) {
        links.add(Uri.tryParse(_baseUrl)?.resolve(href).toString() ?? href);
      }
    }

    return links
        .map((url) {
          final num = getChapterNumber(url);
          return num > 0
              ? Chapter(number: num, url: url, label: num.toString())
              : null;
        })
        .nonNulls
        .toList()
      ..sort((a, b) => a.number.compareTo(b.number));
  }

  @override
  double getChapterNumber(String chapUrl) {
    final m = RegExp(r'&chapter=([\d.]+)', caseSensitive: false).firstMatch(chapUrl);
    if (m == null) return -1;
    return double.tryParse(m.group(1)!) ?? -1;
  }

  @override
  Future<List<String>> getChapterImages(String chapUrl, {bool Function()? isCancelled}) async {
    final html = await _dataSource.fetchHtml(chapUrl);
    final document = parser.parse(html);
    final urls = <String>[];

    for (final img in document.querySelectorAll('img.imgholder')) {
      var src = img.attributes['src'] ?? '';
      if (src.isNotEmpty) {
        src = src.replaceAll('demoniclibs.com', 'librarydm.com');
        urls.add(src);
      }
    }

    return urls;
  }
}
