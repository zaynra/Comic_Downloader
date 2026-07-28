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
  List<String> _allImagePaths = [];
  List<String> _displayedImagePaths = [];
  bool _loading = true;
  static const _pageSize = 10;
  int _shownCount = 0;
  int _totalImages = 0;

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

      _allImagePaths = paths;
      _totalImages = paths.length;
      _shownCount = _pageSize;
      setState(() {
        _displayedImagePaths = _allImagePaths.take(_shownCount).toList();
        _loading = false;
      });
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  void _loadMore() {
    setState(() {
      _shownCount += _pageSize;
      _displayedImagePaths = _allImagePaths.take(_shownCount).toList();
    });
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
          : _displayedImagePaths.isEmpty
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
                  itemCount: _displayedImagePaths.length +
                      (_totalImages > _shownCount ? 2 : 1),
                  itemBuilder: (_, i) {
                    if (i == _displayedImagePaths.length) {
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Center(
                          child: Text('Halaman $_shownCount dari $_totalImages',
                              style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                        ),
                      );
                    }
                    if (i > _displayedImagePaths.length) {
                      return Padding(
                        padding: const EdgeInsets.only(bottom: AppDimensions.spacingMd),
                        child: SizedBox(
                          width: double.infinity,
                          height: 44,
                          child: OutlinedButton.icon(
                            onPressed: _loadMore,
                            icon: const Icon(Icons.expand_more),
                            label: Text('Muat $_pageSize Lagi (${_totalImages - _shownCount} tersisa)'),
                          ),
                        ),
                      );
                    }
                    return Padding(
                      padding: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                        child: GestureDetector(
                          onTap: () => _showFullScreen(i),
                          child: Image.file(
                            File(_displayedImagePaths[i]),
                            fit: BoxFit.contain,
                            frameBuilder: (ctx, child, frame, wasSync) {
                              if (frame == null) {
                                return Container(
                                  height: 200,
                                  color: AppColors.surfaceContainerHigh,
                                  child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
                                );
                              }
                              return child;
                            },
                            errorBuilder: (_, __, ___) => Container(
                              height: 200,
                              color: AppColors.surfaceContainerHigh,
                              child: const Center(child: Icon(Icons.broken_image_outlined)),
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                ),
    );
  }

  void _showFullScreen(int initialIndex) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _FullScreenViewer(
          images: _allImagePaths,
          initialIndex: initialIndex,
          title: widget.seriesTitle,
        ),
      ),
    );
  }

  void _openInComicViewer() {
    try {
      final encodedPath = Uri.encodeComponent(widget.pdfPath);
      final uri = Uri.parse('comic-viewer://open?path=$encodedPath');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Tap untuk buka: $uri'),
          duration: const Duration(seconds: 5),
          action: SnackBarAction(label: 'BUKA', onPressed: () {}),
        ),
      );
    } catch (_) {}
  }
}

class _FullScreenViewer extends StatefulWidget {
  final List<String> images;
  final int initialIndex;
  final String title;
  const _FullScreenViewer({required this.images, required this.initialIndex, required this.title});

  @override
  State<_FullScreenViewer> createState() => _FullScreenViewerState();
}

class _FullScreenViewerState extends State<_FullScreenViewer> {
  late PageController _pageController;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _currentIndex = widget.initialIndex;
    _pageController = PageController(initialPage: _currentIndex);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text('${widget.title} — ${_currentIndex + 1}/${widget.images.length}'),
        centerTitle: true,
      ),
      body: Column(
        children: [
          Expanded(
            child: PageView.builder(
              controller: _pageController,
              itemCount: widget.images.length,
              onPageChanged: (i) => setState(() => _currentIndex = i),
              itemBuilder: (_, i) {
                return InteractiveViewer(
                  minScale: 0.5,
                  maxScale: 4.0,
                  child: Center(
                    child: Image.file(
                      File(widget.images[i]),
                      fit: BoxFit.contain,
                      frameBuilder: (ctx, child, frame, wasSync) {
                        if (frame == null) {
                          return const Center(child: CircularProgressIndicator(color: Colors.white38));
                        }
                        return child;
                      },
                      errorBuilder: (_, __, ___) => const Center(
                        child: Icon(Icons.broken_image_outlined, color: Colors.white54, size: 48),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          if (widget.images.length > 1)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 8),
              color: Colors.black87,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left, color: Colors.white),
                    onPressed: _currentIndex > 0
                        ? () => _pageController.previousPage(
                            duration: const Duration(milliseconds: 200), curve: Curves.easeInOut)
                        : null,
                  ),
                  Text('${_currentIndex + 1} / ${widget.images.length}',
                      style: const TextStyle(color: Colors.white, fontSize: 14)),
                  IconButton(
                    icon: const Icon(Icons.chevron_right, color: Colors.white),
                    onPressed: _currentIndex < widget.images.length - 1
                        ? () => _pageController.nextPage(
                            duration: const Duration(milliseconds: 200), curve: Curves.easeInOut)
                        : null,
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}