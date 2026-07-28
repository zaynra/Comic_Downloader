const chapterPdfPrefix = 'Chapter_';

String formatChapterLabel(double num) {
  if (num == num.roundToDouble()) {
    return '${num.toInt()}'.padLeft(4, '0');
  }
  final str = num.toString();
  final parts = str.split('.');
  final intPart = int.parse(parts[0]);
  final decPart = parts.length > 1 ? parts[1] : '0';
  return '${intPart.toString().padLeft(4, '0')}.$decPart';
}

String formatChapterPdfFilename(String chapterLabel) {
  return '$chapterPdfPrefix$chapterLabel.pdf';
}

double? extractChapterNumber(String name) {
  final m = RegExp(r'(\d+(?:\.\d+)?)').firstMatch(name);
  if (m == null) return null;
  return double.tryParse(m.group(1)!);
}

String sanitizeFilename(String name) {
  return name.replaceAll(RegExp(r'[<>:"/\\|?*]'), '').trim();
}
