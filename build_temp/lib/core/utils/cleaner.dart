import 'dart:io';
import 'dart:math';
import 'package:path/path.dart' as p;
import 'natural_sort.dart';

class ImageEntry {
  final String fileName;
  final int? width;
  final int? height;
  final int? fileSize;

  const ImageEntry(this.fileName, this.width, this.height, this.fileSize);
}

class CleanerResult {
  final int totalDeleted;
  final List<String> deletedFiles;

  const CleanerResult({required this.totalDeleted, required this.deletedFiles});
}

class ImageCleaner {
  static const int widthTolerance = 5;
  static const int confirmRun = 3;
  static const double aspectPercentile = 0.25;
  static const int headerIgnore = 5;

  static Future<CleanerResult> cleanDirectory(String targetPath, {bool dryRun = false}) async {
    final dir = Directory(targetPath);
    if (!await dir.exists()) {
      return const CleanerResult(totalDeleted: 0, deletedFiles: []);
    }

    final imageExts = {'.jpg', '.jpeg', '.png', '.webp'};
    int totalDeleted = 0;
    final allDeleted = <String>[];

    await for (final entity in dir.list(recursive: true)) {
      if (entity is! File) continue;
      final ext = p.extension(entity.path).toLowerCase();
      if (!imageExts.contains(ext)) continue;

      final parentDir = p.dirname(entity.path);
      final allImages = <String>[];
      await for (final e in Directory(parentDir).list()) {
        if (e is File && imageExts.contains(p.extension(e.path).toLowerCase())) {
          allImages.add(p.basename(e.path));
        }
      }
      if (allImages.isEmpty) continue;

      allImages.sort((a, b) {
        final aKey = naturalSortKey(a);
        final bKey = naturalSortKey(b);
        for (int i = 0; i < aKey.length && i < bKey.length; i++) {
          final cmp = aKey[i].compareTo(bKey[i]);
          if (cmp != 0) return cmp;
        }
        return aKey.length.compareTo(bKey.length);
      });
      final entries = await _readDimensions(parentDir, allImages);

      final bodyWidth = _computeReferenceWidth(entries);
      if (bodyWidth == null) continue;

      final minAspect = _computeMinAspectThreshold(entries, bodyWidth);
      final bodyStartIdx = _detectBodyStart(entries, bodyWidth, minAspect);
      if (bodyStartIdx == null) continue;

      final bannerStartIdx = _findBannerStart(entries, bodyStartIdx, bodyWidth, minAspect);

      for (int i = bannerStartIdx; i < entries.length; i++) {
        final filePath = p.join(parentDir, entries[i].fileName);
        if (dryRun) {
          allDeleted.add('[DRY-RUN] ${entries[i].fileName}');
          totalDeleted++;
        } else {
          try {
            await File(filePath).delete();
            allDeleted.add(entries[i].fileName);
            totalDeleted++;
          } catch (_) {}
        }
      }
    }

    return CleanerResult(totalDeleted: totalDeleted, deletedFiles: allDeleted);
  }

  static Future<List<ImageEntry>> _readDimensions(String dir, List<String> images) async {
    final entries = <ImageEntry>[];
    for (final file in images) {
      final filePath = p.join(dir, file);
      try {
        final fileSize = await File(filePath).length();
    final decoded = await _decodeImageDimensions(filePath);
    entries.add(ImageEntry(file, decoded.first, decoded.second, fileSize));
      } catch (_) {
        entries.add(ImageEntry(file, null, null, null));
      }
    }
    return entries;
  }

  static Future<Pair<int?, int?>> _decodeImageDimensions(String filePath) async {
    try {
      final file = await File(filePath).readAsBytes();
      if (file.length < 24) return const Pair(null, null);

      if (file[0] == 0xFF && file[1] == 0xD8) {
        int offset = 2;
        while (offset + 8 < file.length) {
          if (file[offset] == 0xFF && file[offset + 1] == 0xC0) {
            final height = (file[offset + 5] << 8) | file[offset + 6];
            final width = (file[offset + 7] << 8) | file[offset + 8];
            return Pair(width, height);
          }
          offset += 2 + ((file[offset + 2] << 8) | file[offset + 3]);
          if (offset + 1 < file.length && file[offset] == 0xFF) {
            offset++;
          }
        }
      } else if (file[0] == 0x89 && file[1] == 0x50 && file[2] == 0x4E && file[3] == 0x47) {
        int width = 0, height = 0;
        for (int i = 16; i < 20; i++) width = (width << 8) | file[i];
        for (int i = 20; i < 24; i++) height = (height << 8) | file[i];
        return Pair(width, height);
      }
      return const Pair(null, null);
    } catch (_) {
      return const Pair(null, null);
    }
  }

  static int? _computeReferenceWidth(List<ImageEntry> entries) {
    final counts = <int, int>{};
    final start = entries.length > headerIgnore ? headerIgnore : 0;
    for (int i = start; i < entries.length; i++) {
      final w = entries[i].width;
      if (w != null) counts[w] = (counts[w] ?? 0) + 1;
    }
    if (counts.isEmpty) return null;
    return counts.entries.reduce((a, b) => a.value >= b.value ? a : b).key;
  }

  static double _computeMinAspectThreshold(List<ImageEntry> entries, int bodyWidth) {
    final aspects = <double>[];
    for (final e in entries) {
      if (e.width != null && e.height != null && e.width! > 0 &&
          (e.width! - bodyWidth).abs() <= widthTolerance) {
        aspects.add(e.height! / e.width!);
      }
    }
    if (aspects.isEmpty) return 0.0;
    aspects.sort();
    final idx = min((aspects.length * aspectPercentile).toInt(), aspects.length - 1);
    return aspects[idx];
  }

  static bool _isBodyPage(int? w, int? h, int bodyWidth, double minAspect) {
    if (w == null || h == null || w == 0) return false;
    if ((w - bodyWidth).abs() > widthTolerance) return false;
    return (h / w) >= minAspect;
  }

  static int? _detectBodyStart(List<ImageEntry> entries, int bodyWidth, double minAspect) {
    for (int i = 0; i < entries.length; i++) {
      if (_isBodyPage(entries[i].width, entries[i].height, bodyWidth, minAspect)) {
        return i;
      }
    }
    return null;
  }

  static int _findBannerStart(List<ImageEntry> entries, int bodyStartIdx, int bodyWidth, double minAspect) {
    if (bodyStartIdx >= entries.length) return entries.length;

    int streak = 0;
    int bannerStartIdx = entries.length;

    for (int i = entries.length - 1; i >= bodyStartIdx; i--) {
      if (_isBodyPage(entries[i].width, entries[i].height, bodyWidth, minAspect)) {
        streak++;
        if (streak >= confirmRun) {
          bannerStartIdx = i + 1;
          break;
        }
      } else {
        streak = 0;
      }
    }

    if (bannerStartIdx == entries.length) {
      bannerStartIdx = bodyStartIdx;
    }

    return bannerStartIdx;
  }
}

class Pair<T1, T2> {
  final T1 first;
  final T2 second;
  const Pair(this.first, this.second);
}
