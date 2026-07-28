import 'chapter.dart';

class DownloadJob {
  final String id;
  final String seriesTitle;
  final String seriesUrl;
  final String adapterName;
  final List<Chapter> chapters;
  final String outputFolder;
  bool isCancelled;
  bool isPaused;
  DateTime? startedAt;
  DateTime? completedAt;

  DownloadJob({
    required this.id,
    required this.seriesTitle,
    required this.seriesUrl,
    required this.adapterName,
    required this.chapters,
    required this.outputFolder,
    this.isCancelled = false,
    this.isPaused = false,
    this.startedAt,
    this.completedAt,
  });

  int get totalChapters => chapters.length;
  int get completedChapters => chapters.where((c) => c.status == ChapterStatus.completed).length;
  int get failedChapters => chapters.where((c) => c.status == ChapterStatus.failed).length;
  bool get isDone => completedChapters + failedChapters == totalChapters;
}
