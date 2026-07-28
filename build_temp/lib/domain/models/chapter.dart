enum ChapterStatus { pending, downloading, completed, failed, skipped }

class Chapter {
  final double number;
  final String url;
  final String label;
  ChapterStatus status;
  String? pdfPath;
  int progressPages;
  int totalPages;

  Chapter({
    required this.number,
    required this.url,
    required this.label,
    this.status = ChapterStatus.pending,
    this.pdfPath,
    this.progressPages = 0,
    this.totalPages = 0,
  });
}
