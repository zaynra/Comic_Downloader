class Series {
  final String id;
  final String title;
  final String url;
  final String? thumbnailUrl;
  final String? author;
  final String? genre;
  final int? chapterCount;
  final String adapterName;

  const Series({
    required this.id,
    required this.title,
    required this.url,
    this.thumbnailUrl,
    this.author,
    this.genre,
    this.chapterCount,
    required this.adapterName,
  });
}
