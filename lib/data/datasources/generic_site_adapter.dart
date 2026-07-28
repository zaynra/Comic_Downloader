import 'package:html/parser.dart' as parser;
import 'package:html/dom.dart' as dom;
import '../../domain/repositories/site_adapter.dart';
import '../../domain/models/series.dart';
import '../../domain/models/chapter.dart';
import 'remote_data_source.dart';

class GenericSiteAdapter implements BaseSiteAdapter {
  final RemoteDataSource _dataSource;

  @override
  final String name = 'generic';

  static final _chapterLinkPattern = RegExp(r'(chapter|ch|c|ep)/?.*?\d', caseSensitive: false);
  static final _chapterNumPattern = RegExp(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', caseSensitive: false);

  static const _blockedKeywords = [
    'banner', 'logo', 'icon', 'favicon', 'avatar', 'ads',
    'recommend', 'thumbnail', 'cover', 'header', 'footer',
    'social', 'discord', 'comment', 'profile', 'placeholder',
    'loading', 'spinner', 'related', 'sidebar', 'widget',
    'promo', 'sponsor', 'patreon', 'kofi', 'ko-fi',
    'telegram', 'whatsapp', 'twitter', 'facebook', 'instagram',
    'navigation', 'watermark', 'nextchapter', 'prevchapter',
  ];

  static const _endMarkers = [
    'enddesign', 'end-of-chapter', 'endchapter', 'endpage',
    'thankyou', 'supportus', 'followus', 'read-next',
    'joinourdiscord', 'closing', 'outro', 'omake-end',
  ];

  static const _validImgExt = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];

  static const _chapterImagePattern = r'/(chapters|chapter|pages?)/.*?\.(webp|jpg|jpeg|png)';

  GenericSiteAdapter({RemoteDataSource? dataSource})
      : _dataSource = dataSource ?? RemoteDataSource();

  @override
  Future<List<Series>> search(String query) async {
    final html = await _dataSource.fetchHtml(
      'https://www.google.com/search?q=$query+comic+chapter',
    );
    final document = parser.parse(html);
    final results = <Series>[];
    for (final link in document.querySelectorAll('a[href]')) {
      final href = link.attributes['href'] ?? '';
      if (_chapterLinkPattern.hasMatch(href)) {
        results.add(Series(
          id: Uri.tryParse(href)?.pathSegments.last ?? href,
          title: link.text.trim(),
          url: href,
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
      document.querySelector('.series-name'),
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
    final links = <String>[];
    final seen = <String>{};

    for (final a in document.querySelectorAll('a[href]')) {
      final href = a.attributes['href'] ?? '';
      if (!_chapterLinkPattern.hasMatch(href)) continue;
      final fullUrl = Uri.tryParse(seriesUrl)?.resolve(href).toString() ?? href;
      if (seen.add(fullUrl)) {
        links.add(fullUrl);
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
    final m = _chapterNumPattern.firstMatch(chapUrl);
    if (m == null) return -1;
    return double.tryParse(m.group(1)!) ?? -1;
  }

  @override
  Future<List<String>> getChapterImages(String chapUrl, {bool Function()? isCancelled}) async {
    final html = await _dataSource.fetchHtml(chapUrl);
    final document = parser.parse(html);

    for (final sel in _excludeSelectors) {
      for (final el in document.querySelectorAll(sel)) {
        el.remove();
      }
    }

    dom.Element reader;
    dom.Element? found;
    for (final sel in _readerSelectors) {
      found = document.querySelector(sel);
      if (found != null) break;
    }
    reader = found ?? document.body!;
    final urls = _extractSequentialImages(reader, chapUrl);
    return urls;
  }

  List<String> _extractSequentialImages(dom.Element reader, String baseUrl) {
    final urls = <String>[];
    int validCount = 0;
    int invalidStreak = 0;
    const maxInvalidStreak = 5;

    void processNode(dom.Node node) {
      if (node is dom.Text) {
        final text = node.text.trim().toLowerCase();
        if (text.isNotEmpty && text.length <= 120) {
          if (_textEndMarkers.any((m) => text.contains(m))) {
            if (validCount > 0) return;
          }
        }
        return;
      }

      if (node is! dom.Element || node.localName != 'img') {
        for (final child in node.nodes) {
          processNode(child);
        }
        return;
      }

      final img = node;
      final src = img.attributes['src'] ??
          img.attributes['data-src'] ??
          img.attributes['data-lazy-src'] ??
          img.attributes['data-original'];

      if (src == null || src.trim().isEmpty) {
        for (final child in node.nodes) {
          processNode(child);
        }
        return;
      }

      final url = Uri.tryParse(baseUrl)?.resolve(src.trim()).toString() ?? src.trim();
      final low = url.toLowerCase();

      if (_endMarkers.any((m) => low.contains(m))) {
        if (validCount > 0) return;
        for (final child in node.nodes) {
          processNode(child);
        }
        return;
      }

      if (!_isValidPageImage(url)) {
        invalidStreak++;
        if (invalidStreak >= maxInvalidStreak && validCount > 0) return;
        for (final child in node.nodes) {
          processNode(child);
        }
        return;
      }

      if (_blockedKeywords.any((k) => low.contains(k))) {
        invalidStreak++;
        invalidStreak++;
        if (invalidStreak >= maxInvalidStreak && validCount > 0) return;
        for (final child in node.nodes) {
          processNode(child);
        }
        return;
      }

      urls.add(url);
      validCount++;
      invalidStreak = 0;

      for (final child in node.nodes) {
        processNode(child);
      }
    }

    processNode(reader);
    return urls..sort();
  }

  bool _isValidPageImage(String url) {
    final low = url.toLowerCase();
    final path = Uri.tryParse(low)?.path ?? '';
    final basename = path.split('/').last;

    for (final kw in _blockedKeywords) {
      final pattern = '(?:^|[^a-z0-9])${RegExp.escape(kw)}(?:[^a-z0-9]|' r'$)';
      if (RegExp(pattern, caseSensitive: false).hasMatch(basename)) {
        return false;
      }
    }

    if (RegExp(_chapterImagePattern, caseSensitive: false).hasMatch(low)) {
      return true;
    }

    final ext = '.${path.split('.').last}';
    return _validImgExt.contains(ext);
  }

  static const _readerSelectors = [
    'div#readerarea',
    'div.reading-content',
    'div.reader-area',
    'div.chapter-content',
    'section#chapter',
    'div.chapter-images',
    'div.container-chapter-reader',
    'div.page-break',
    'div[class*="reader"]',
    'div[id*="reader"]',
    'main',
  ];

  static const _excludeSelectors = [
    'div.comments',
    'div#comments',
    'div#disqus_thread',
    'section.comments',
    'div.share-buttons',
    'div.social-share',
    'div.related',
    'div.related-posts',
    'div.you-may-like',
    'div.recommended',
    'div.rekomendasi',
    'aside',
    'nav',
    'footer',
    'div.navigation',
    'div.chapter-nav',
    'div.chapternav',
    'div.next-prev',
    'div.pagination',
    'div.sidebar',
    'div.widget',
    'div.ads',
    'div.advertisement',
    'ins.adsbygoogle',
    'div.patreon',
    'div.kofi',
    'div.discord-widget',
    'img.emoji',
    'img.wp-smiley',
  ];

  static const _textEndMarkers = [
    'end chapter', 'end of chapter', 'thanks for reading',
    'thank you for reading', 'read next', 'recommended for you',
    'join discord', 'support us', 'next chapter', 'previous chapter',
  ];
}
