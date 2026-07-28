import 'dart:io';
import 'package:path/path.dart' as p;
import '../../core/utils/natural_sort.dart';

const _maxPdfPageHeight = 65000;

class PdfConverter {
  Future<String?> convertChapterToPdf({
    required String chapterDir,
    required String outputPath,
  }) async {
    final imagePaths = _collectImagesFromFolder(chapterDir);
    if (imagePaths.isEmpty) return null;

    final refWidth = _computeReferenceSize(imagePaths);
    if (refWidth == null) return null;

    final success = await _buildLongStripPdf(imagePaths, refWidth, outputPath);
    return success ? outputPath : null;
  }

  List<String> _collectImagesFromFolder(String folder) {
    final dir = Directory(folder);
    if (!dir.existsSync()) return [];

    var files = dir.listSync().whereType<File>().toList();
    files.sort((a, b) {
      final aName = p.basename(a.path);
      final bName = p.basename(b.path);
      final aKey = naturalSortKey(aName);
      final bKey = naturalSortKey(bName);
      for (int i = 0; i < aKey.length && i < bKey.length; i++) {
        final cmp = aKey[i].compareTo(bKey[i]);
        if (cmp != 0) return cmp;
      }
      return aKey.length.compareTo(bKey.length);
    });

    return files
        .where((f) => _isImageFile(f.path))
        .map((f) => f.path)
        .toList();
  }

  bool _isImageFile(String path) {
    final ext = p.extension(path).toLowerCase();
    return ['.jpg', '.jpeg', '.png', '.webp', '.gif'].contains(ext);
  }

  int? _computeReferenceSize(List<String> imagePaths) {
    int? maxWidth;
    for (final path in imagePaths) {
      try {
        final file = File(path);
        final bytes = file.readAsBytesSync();
        final width = _parseImageWidth(bytes);
        if (width != null) {
          maxWidth = maxWidth == null ? width : (width > maxWidth ? width : maxWidth);
        }
      } catch (_) {}
    }
    return maxWidth;
  }

  int? _parseImageWidth(List<int> bytes) {
    try {
      if (bytes.length < 24) return null;
      if (bytes[0] == 0xFF && bytes[1] == 0xD8) {
        int offset = 2;
        while (offset < bytes.length - 1) {
          if (bytes[offset] == 0xFF && bytes[offset + 1] == 0xC0) {
            return (bytes[offset + 7] << 8) | bytes[offset + 8];
          }
          if (bytes[offset] != 0xFF) break;
          offset += 2 + ((bytes[offset + 2] << 8) | bytes[offset + 3]);
        }
      }
      if (bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4E && bytes[3] == 0x47) {
        int offset = 16;
        if (bytes.length >= offset + 8) {
          return ((bytes[offset] << 24) | (bytes[offset + 1] << 16) |
              (bytes[offset + 2] << 8) | bytes[offset + 3]);
        }
      }
    } catch (_) {}
    return null;
  }

  Future<bool> _buildLongStripPdf(
    List<String> imagePaths,
    int refWidth,
    String outputPath,
  ) async {
    final dir = Directory(p.dirname(outputPath));
    if (!dir.existsSync()) {
      dir.createSync(recursive: true);
    }

    try {
      final pdfBytes = await _createPdfBytes(imagePaths, refWidth);
      if (pdfBytes == null) return false;
      await File(outputPath).writeAsBytes(pdfBytes);
      return true;
    } catch (e) {
      return false;
    }
  }

  Future<List<int>?> _createPdfBytes(List<String> imagePaths, int refWidth) async {
    final pages = <List<int>>[];
    int currentHeight = 0;
    var currentPage = <String>[];

    for (final path in imagePaths) {
      final file = File(path);
      final bytes = file.readAsBytesSync();
      final height = _estimateImageHeight(bytes, refWidth);

      if (height != null && currentHeight + height > _maxPdfPageHeight && currentPage.isNotEmpty) {
        final pageBytes = await _renderPage(currentPage, refWidth);
        if (pageBytes != null) pages.add(pageBytes);
        currentPage = [path];
        currentHeight = height;
      } else {
        currentPage.add(path);
        currentHeight += height ?? refWidth;
      }
    }

    if (currentPage.isNotEmpty) {
      final pageBytes = await _renderPage(currentPage, refWidth);
      if (pageBytes != null) pages.add(pageBytes);
    }

    return _mergePdfPages(pages);
  }

  int? _estimateImageHeight(List<int> bytes, int refWidth) {
    try {
      if (bytes.length < 24) return null;
      if (bytes[0] == 0xFF && bytes[1] == 0xD8) {
        int offset = 2;
        while (offset < bytes.length - 1) {
          if (bytes[offset] == 0xFF) {
            if (bytes[offset + 1] == 0xC0 || bytes[offset + 1] == 0xC2) {
              final h = (bytes[offset + 5] << 8) | bytes[offset + 6];
              final w = (bytes[offset + 7] << 8) | bytes[offset + 8];
              return (h * refWidth / w).round();
            }
            if (bytes[offset + 1] == 0xD9) break;
            offset += 2 + ((bytes[offset + 2] << 8) | bytes[offset + 3]);
          } else {
            break;
          }
        }
      }
      if (bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4E && bytes[3] == 0x4E) {
        int offset = 16;
        if (bytes.length >= offset + 8) {
          final w = ((bytes[offset] << 24) | (bytes[offset + 1] << 16) |
              (bytes[offset + 2] << 8) | bytes[offset + 3]);
          final h = ((bytes[offset + 4] << 24) | (bytes[offset + 5] << 16) |
              (bytes[offset + 6] << 8) | bytes[offset + 7]);
          return (h * refWidth / w).round();
        }
      }
    } catch (_) {}
    return null;
  }

  Future<List<int>?> _renderPage(List<String> imagePaths, int refWidth) async {
    final images = <List<int>>[];
    for (final path in imagePaths) {
      images.add(File(path).readAsBytesSync());
    }

    final buffer = StringBuffer();
    buffer.writeln('%PDF-1.4');

    final objects = <String>[];
    int objNum = 1;

    for (final imgBytes in images) {
      final w = _parseImageWidth(imgBytes) ?? refWidth;
      final h = _estimateImageHeight(imgBytes, refWidth) ?? refWidth;

      objects.add('$objNum 0 obj\n<< /Type /Page /Parent 3 0 R /MediaBox [0 0 $w $h] '
          '/Contents ${objNum + 1} 0 R /Resources << /XObject << /Im0 ${objNum + 2} 0 R >> >> >> endobj');
      objNum++;

      final stream = 'q ${w} 0 0 ${h} 0 0 cm /Im0 Do Q';
      objects.add('$objNum 0 obj\n<< /Length ${stream.length} >> stream\n$stream\nendstream');
      objNum++;

      objects.add('$objNum 0 obj\n<< /Type /XObject /Subtype /Image /Width $w /Height $h '
          '/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode '
          '/Length ${imgBytes.length} >> stream\n${String.fromCharCodes(imgBytes)}\nendstream');
      objNum++;
    }

    final kids = <String>[];
    for (int i = 1; i < objNum; i += 3) {
      kids.add('$i 0 R');
    }

    final pagesObj = '$objNum 0 obj\n<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${images.length} >> endobj';
    objNum++;

    final catalog = '$objNum 0 obj\n<< /Type /Catalog /Pages ${objNum - 1} 0 R >> endobj';
    objNum++;

    buffer.writeln(objects.join('\n'));
    buffer.writeln(pagesObj);
    buffer.writeln(catalog);

    final xrefOffset = buffer.toString().length;
    buffer.writeln('xref');
    buffer.writeln('0 $objNum');
    buffer.writeln('0000000000 65535 f ');
    int pos = 0;
    for (int i = 0; i < objects.length; i++) {
      final objStr = objects[i];
      buffer.writeln('$pos'.padLeft(10, '0') + ' 00000 n ');
      pos += objStr.length + 1;
    }
    final pagesStr = pagesObj;
    buffer.writeln('$pos'.padLeft(10, '0') + ' 00000 n ');
    pos += pagesStr.length + 1;
    buffer.writeln('$pos'.padLeft(10, '0') + ' 00000 n ');

    buffer.writeln('trailer\n<< /Size $objNum /Root $objNum 0 R >>');
    buffer.writeln('startxref\n$xrefOffset\n%%EOF');

    return buffer.toString().codeUnits;
  }

  Future<List<int>?> _mergePdfPages(List<List<int>> pages) async {
    if (pages.isEmpty) return null;
    if (pages.length == 1) return pages.first;

    final buffer = StringBuffer();
    buffer.writeln('%PDF-1.4');

    int objNum = 1;
    final objects = <String>[];
    final kids = <String>[];

    for (final pageBytes in pages) {
      final pageStr = String.fromCharCodes(pageBytes);
      final pageSize = _extractPageSize(pageStr);

      objects.add('$objNum 0 obj\n<< /Type /Page /Parent 3 0 R '
          '/MediaBox [0 0 ${pageSize['w'] ?? 612} ${pageSize['h'] ?? 792}] '
          '/Contents ${objNum + 1} 0 R '
          '/Resources << /XObject << /Im0 ${objNum + 2} 0 R >> >> >> endobj');
      objNum++;

      final stream = 'q ${pageSize['w'] ?? 612} 0 0 ${pageSize['h'] ?? 792} 0 0 cm /Im0 Do Q';
      objects.add('$objNum 0 obj\n<< /Length ${stream.length} >> stream\n$stream\nendstream');
      objNum++;

      final imgData = _extractImageData(pageStr);
      if (imgData != null) {
        objects.add('$objNum 0 obj\n<< /Type /XObject /Subtype /Image '
            '/Width ${imgData['w']} /Height ${imgData['h']} '
            '/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode '
            '/Length ${imgData['data'].length} >> stream\n${imgData['data']}\nendstream');
      }
      objNum++;

      kids.add('${objNum - 3} 0 R');
    }

    objects.add('$objNum 0 obj\n<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${kids.length} >> endobj');
    objNum++;

    objects.add('$objNum 0 obj\n<< /Type /Catalog /Pages ${objNum - 1} 0 R >> endobj');
    objNum++;

    buffer.writeln(objects.join('\n'));

    final xrefOffset = buffer.toString().length;
    buffer.writeln('xref');
    buffer.writeln('0 $objNum');
    buffer.writeln('0000000000 65535 f ');
    int pos = 0;
    for (final obj in objects) {
      buffer.writeln('$pos'.padLeft(10, '0') + ' 00000 n ');
      pos += obj.length + 1;
    }

    buffer.writeln('trailer\n<< /Size $objNum /Root ${objNum - 1} 0 R >>');
    buffer.writeln('startxref\n$xrefOffset\n%%EOF');

    return buffer.toString().codeUnits;
  }

  Map<String, dynamic> _extractPageSize(String pdfContent) {
    final m = RegExp(r'/MediaBox\s*\[0 0 (\d+) (\d+)\]').firstMatch(pdfContent);
    if (m != null) {
      return {'w': int.tryParse(m.group(1)!), 'h': int.tryParse(m.group(2)!)};
    }
    return {'w': 612, 'h': 792};
  }

  Map<String, dynamic>? _extractImageData(String pdfContent) {
    final m = RegExp(r'/Width (\d+).*?/Height (\d+).*?stream\n(.+?)\nendstream',
        dotAll: true).firstMatch(pdfContent);
    if (m != null) {
      return {
        'w': int.tryParse(m.group(1)!),
        'h': int.tryParse(m.group(2)!),
        'data': m.group(3)!,
      };
    }
    return null;
  }
}
