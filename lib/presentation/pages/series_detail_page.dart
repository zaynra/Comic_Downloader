import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:path/path.dart' as p;
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../data/datasources/adapter_resolver.dart';
import '../../domain/models/chapter.dart';
import '../providers/download_provider.dart';

class SeriesDetailPage extends ConsumerStatefulWidget {
  final String seriesId;

  const SeriesDetailPage({super.key, required this.seriesId});

  @override
  ConsumerState<SeriesDetailPage> createState() => _SeriesDetailPageState();
}

class _SeriesDetailPageState extends ConsumerState<SeriesDetailPage> {
  final Set<double> _selectedChapters = {};
  List<Chapter> _chapters = [];
  String _title = '';
  bool _loading = true;
  String? _error;
  Set<double> _existingChapters = {};

  @override
  void initState() {
    super.initState();
    _loadChapters();
  }

  Future<void> _loadChapters() async {
    final seriesUrl = Uri.decodeComponent(widget.seriesId);
    try {
      final adapter = resolveAdapter(seriesUrl);
      final title = await adapter.getTitle(seriesUrl);
      final chapters = await adapter.getChapters(seriesUrl);
      final existing = await _detectExistingChapters(title);

      if (!mounted) return;
      setState(() {
        _title = title;
        _chapters = chapters;
        _existingChapters = existing;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Gagal memuat data: ${e.toString().length > 100 ? e.toString().substring(0, 100) : e.toString()}';
      });
    }
  }

  Future<Set<double>> _detectExistingChapters(String seriesTitle) async {
    final prefs = await SharedPreferences.getInstance();
    final outputFolder = prefs.getString('output_folder');
    if (outputFolder == null || outputFolder.isEmpty) return {};

    final seriesDir = p.join(outputFolder, seriesTitle);
    final resultDir = p.join(seriesDir, 'Result');
    final resultDir2 = Directory(resultDir);

    if (!await resultDir2.exists()) return {};

    final existing = <double>{};
    try {
      await for (final file in resultDir2.list()) {
        final name = p.basenameWithoutExtension(file.path);
        final match = RegExp(r'Chapter_(\d+)').firstMatch(name);
        if (match != null) {
          existing.add(double.parse(match.group(1)!));
        }
      }
    } catch (_) {}

    return existing;
  }

  Future<void> _downloadSelected() async {
    if (_selectedChapters.isEmpty) return;

    final repo = ref.read(downloadRepositoryProvider);
    final seriesUrl = Uri.decodeComponent(widget.seriesId);
    final adapter = resolveAdapter(seriesUrl);
    final prefs = await SharedPreferences.getInstance();
    final outputFolder = prefs.getString('output_folder') ?? '';

    if (outputFolder.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Atur folder output dulu di Pengaturan')),
      );
      return;
    }

    final job = await repo.createJob(
      seriesUrl: seriesUrl,
      seriesTitle: _title,
      adapterName: adapter.name,
      chapterNumbers: _selectedChapters.toList()..sort(),
      outputFolder: outputFolder,
    );

    repo.startJob(job);
    if (context.mounted) context.push('/queue');
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(_title.isNotEmpty ? _title : 'Detail Series'),
        centerTitle: true,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(AppDimensions.spacingMd),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.error_outline, size: 48, color: AppColors.error.withValues(alpha: 0.7)),
                        const SizedBox(height: AppDimensions.spacingMd),
                        Text(_error!, style: textTheme.bodyMedium, textAlign: TextAlign.center),
                        const SizedBox(height: AppDimensions.spacingLg),
                        FilledButton.icon(
                          onPressed: () {
                            setState(() { _loading = true; _error = null; });
                            _loadChapters();
                          },
                          icon: const Icon(Icons.refresh),
                          label: const Text('Coba Lagi'),
                        ),
                      ],
                    ),
                  ),
                )
              : _chapters.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.auto_stories_outlined, size: 64,
                              color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                          const SizedBox(height: AppDimensions.spacingMd),
                          Text('Tidak ada chapter ditemukan', style: textTheme.bodyLarge?.copyWith(
                              color: AppColors.onSurfaceVariant)),
                        ],
                      ),
                    )
                  : Column(
                      children: [
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppDimensions.spacingMd,
                            vertical: AppDimensions.spacingSm,
                          ),
                          child: Row(
                            children: [
                              Text('${_chapters.length} chapter', style: textTheme.bodySmall),
                              if (_existingChapters.isNotEmpty)
                                Padding(
                                  padding: const EdgeInsets.only(left: AppDimensions.spacingSm),
                                  child: Text('(${_existingChapters.length} sudah ada)',
                                      style: textTheme.bodySmall?.copyWith(color: AppColors.secondary)),
                                ),
                              const Spacer(),
                              TextButton(
                                onPressed: _downloadFromLastSaved,
                                child: Text('Lanjutkan', style: TextStyle(color: AppColors.secondary)),
                              ),
                              TextButton(
                                onPressed: () {
                                  setState(() {
                                    if (_selectedChapters.length == _chapters.length) {
                                      _selectedChapters.clear();
                                    } else {
                                      _selectedChapters.addAll(_chapters.map((c) => c.number));
                                    }
                                  });
                                },
                                child: Text(_selectedChapters.length == _chapters.length
                                    ? 'Unselect All' : 'Select All'),
                              ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: ListView.builder(
                            itemCount: _chapters.length,
                            itemBuilder: (_, i) {
                              final chapter = _chapters[i];
                              final isSelected = _selectedChapters.contains(chapter.number);
                              final isExisting = _existingChapters.contains(chapter.number);
                              return CheckboxListTile(
                                value: isSelected || isExisting,
                                tristate: isExisting,
                                title: Text('Chapter ${chapter.label}',
                                    style: isExisting ? TextStyle(color: AppColors.secondary) : null),
                                subtitle: Text(isExisting ? 'Sudah ada di folder' : chapter.number.toString(),
                                    style: textTheme.bodySmall),
                                enabled: !isExisting,
                                onChanged: isExisting
                                    ? null
                                    : (v) {
                                        setState(() {
                                          if (v == true) {
                                            _selectedChapters.add(chapter.number);
                                          } else {
                                            _selectedChapters.remove(chapter.number);
                                          }
                                        });
                                      },
                              );
                            },
                          ),
                        ),
                        if (_selectedChapters.isNotEmpty)
                          Container(
                            padding: const EdgeInsets.all(AppDimensions.spacingMd),
                            decoration: BoxDecoration(
                              color: AppColors.surfaceContainerLow,
                              border: Border(
                                top: BorderSide(color: AppColors.outlineVariant.withValues(alpha: 0.5)),
                              ),
                            ),
                            child: SafeArea(
                              child: SizedBox(
                                width: double.infinity,
                                height: 48,
                                child: FilledButton.icon(
                                  onPressed: _downloadSelected,
                                  icon: const Icon(Icons.download),
                                  label: Text('Download ${_selectedChapters.length} Chapter'),
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
    );
  }

  void _downloadFromLastSaved() {
    if (_existingChapters.isEmpty) {
      _selectedChapters.addAll(_chapters.map((c) => c.number));
      return;
    }
    final maxExisting = _existingChapters.reduce((a, b) => a > b ? a : b);
    final newChapters = _chapters
        .where((c) => c.number > maxExisting && !_existingChapters.contains(c.number))
        .map((c) => c.number)
        .toList();
    setState(() => _selectedChapters.addAll(newChapters));
  }
}
