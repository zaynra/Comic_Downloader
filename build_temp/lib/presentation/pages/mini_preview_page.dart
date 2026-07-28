import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../core/utils/natural_sort.dart';

class MiniPreviewPage extends StatefulWidget {
  final String pdfPath;
  final String seriesTitle;

  const MiniPreviewPage({
    super.key,
    required this.pdfPath,
    required this.seriesTitle,
  });

  @override
  State<MiniPreviewPage> createState() => _MiniPreviewPageState();
}

class _MiniPreviewPageState extends State<MiniPreviewPage> {
  List<String> _imagePaths = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadPreview();
  }

  Future<void> _loadPreview() async {
    try {
      final dir = p.dirname(widget.pdfPath);
      final resultDir = p.join(dir, 'Result');
      final resultImagesDir = p.join(resultDir, 'images');

      List<String> paths;
      if (await Directory(resultImagesDir).exists()) {
        paths = await Directory(resultImagesDir)
            .list()
            .where((e) => e is File)
            .map((e) => e.path)
            .toList();
      } else {
        final pdfDir = p.dirname(widget.pdfPath);
        final files = await Directory(pdfDir)
            .list()
            .where((e) => e is File && ['.jpg', '.jpeg', '.png'].contains(p.extension(e.path).toLowerCase()))
            .map((e) => e.path)
            .toList();
        paths = files;
      }

      paths.sort((a, b) {
        final aKey = naturalSortKey(p.basename(a));
        final bKey = naturalSortKey(p.basename(b));
        for (int i = 0; i < aKey.length && i < bKey.length; i++) {
          final cmp = aKey[i].compareTo(bKey[i]);
          if (cmp != 0) return cmp;
        }
        return aKey.length.compareTo(bKey.length);
      });

      setState(() {
        _imagePaths = paths.take(5).toList();
        _loading = false;
      });
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.seriesTitle),
        actions: [
          TextButton.icon(
            onPressed: _openInComicViewer,
            icon: const Icon(Icons.open_in_new),
            label: const Text('Buka di Comic Viewer'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _imagePaths.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.image_not_supported_outlined,
                          size: 64, color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                      const SizedBox(height: AppDimensions.spacingMd),
                      Text('Tidak ada preview tersedia',
                          style: textTheme.bodyLarge?.copyWith(color: AppColors.onSurfaceVariant)),
                      const SizedBox(height: AppDimensions.spacingLg),
                      FilledButton.icon(
                        onPressed: _openInComicViewer,
                        icon: const Icon(Icons.open_in_new),
                        label: const Text('Buka PDF di Comic Viewer'),
                      ),
                    ],
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(AppDimensions.spacingMd),
                  itemCount: _imagePaths.length,
                  itemBuilder: (_, i) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                        child: Image.file(
                          File(_imagePaths[i]),
                          fit: BoxFit.contain,
                          errorBuilder: (_, __, ___) => Container(
                            height: 200,
                            color: AppColors.surfaceContainerHigh,
                            child: const Center(child: Icon(Icons.broken_image_outlined)),
                          ),
                        ),
                      ),
                    );
                  },
                ),
    );
  }

  void _openInComicViewer() {
    // Attempt deep link to Comic Viewer
    // Comic Viewer uses scheme: comic-viewer://open?path=<encoded-path>
    try {
      final encodedPath = Uri.encodeComponent(widget.pdfPath);
      final uri = Uri.parse('comic-viewer://open?path=$encodedPath');
      // Cannot launch directly in Flutter without url_launcher
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Tap untuk buka: $uri'),
          action: SnackBarAction(label: 'BUKA', onPressed: () {}),
        ),
      );
    } catch (_) {}
  }
}
