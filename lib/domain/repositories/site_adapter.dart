import '../models/series.dart';
import '../models/chapter.dart';

abstract class BaseSiteAdapter {
  String get name;

  Future<List<Series>> search(String query);

  Future<String> getTitle(String seriesUrl);

  Future<List<Chapter>> getChapters(String seriesUrl);

  double getChapterNumber(String chapUrl);

  Future<List<String>> getChapterImages(String chapUrl, {bool Function()? isCancelled});
}
