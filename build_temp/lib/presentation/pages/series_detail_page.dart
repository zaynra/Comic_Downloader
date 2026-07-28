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

enum ChapterSortOrder { ascending, descending }

class _SeriesDetailPageState extends ConsumerState<SeriesDetailPage> {
  final Set<double> _selectedChapters = {};
  List<Chapter> _allChapters = [];
  List<Chapter> _filteredChapters = [];
  String _title = '';
  bool _loading = true;
  String? _error;
  Set<double> _existingChapters = {};
  ChapterSortOrder _sortOrder = ChapterSortOrder.ascending;
  String _chapterFilter = '';
  final _filterController = TextEditingController();
  final _rangeFromController = TextEditingController();
  final _rangeToController = TextEditingController();
  double? _rangeStart;
  bool _showQuickButtons = true;
  bool _showRangeSelector = false;
  int _rangePreviewCount = 0;

  @override
  void initState() {
    super.initState();
    _loadChapters();
  }

  @override
  void dispose() {
    _filterController.dispose();
    _rangeFromController.dispose();
    _rangeToController.dispose();
    super.dispose();
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
        _allChapters = chapters;
        _existingChapters = existing;
        _loading = false;
      });
      _applyFilter();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Gagal memuat data: ${e.toString().length > 200 ? e.toString().substring(0, 200) : e.toString()}';
      });
    }
  }

  void _applyFilter() {
    final sorted = List<Chapter>.from(_allChapters);
    if (_sortOrder == ChapterSortOrder.descending) {
      sorted.sort((a, b) => b.number.compareTo(a.number));
    } else {
      sorted.sort((a, b) => a.number.compareTo(b.number));
    }

    setState(() {
      if (_chapterFilter.isEmpty) {
        _filteredChapters = sorted;
      } else {
        final q = _chapterFilter.toLowerCase();
        _filteredChapters = sorted.where((c) =>
          c.label.toLowerCase().contains(q) ||
          c.number.toString().contains(q)
        ).toList();
      }
    });
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
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Atur folder output dulu di Pengaturan')),
        );
      }
      return;
    }

    final selectedChapters = _allChapters
        .where((c) => _selectedChapters.contains(c.number))
        .toList()
      ..sort((a, b) => a.number.compareTo(b.number));

    try {
      final job = await repo.createJob(
        seriesUrl: seriesUrl,
        seriesTitle: _title,
        adapterName: adapter.name,
        chapters: selectedChapters,
        outputFolder: outputFolder,
      );

      repo.startJob(job);
      if (context.mounted) context.push('/queue');
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Gagal membuat job: $e'), backgroundColor: AppColors.error),
        );
      }
    }
  }

  void _selectAll() {
    setState(() {
      _selectedChapters.addAll(
        _allChapters.where((c) => !_existingChapters.contains(c.number)).map((c) => c.number),
      );
    });
  }

  void _deselectAll() {
    setState(() => _selectedChapters.clear());
  }

  void _invertSelection() {
    setState(() {
      final allSelectable = _allChapters.where((c) => !_existingChapters.contains(c.number)).map((c) => c.number).toSet();
      final inverted = allSelectable.difference(_selectedChapters);
      _selectedChapters.clear();
      _selectedChapters.addAll(inverted);
    });
  }

  void _selectNewOnly() {
    setState(() {
      _selectedChapters.clear();
      _selectedChapters.addAll(
        _allChapters.where((c) => !_existingChapters.contains(c.number)).map((c) => c.number),
      );
    });
  }

  void _selectFromLastSaved() {
    if (_existingChapters.isEmpty) {
      _selectAll();
      return;
    }
    final maxExisting = _existingChapters.reduce((a, b) => a > b ? a : b);
    setState(() {
      _selectedChapters.clear();
      _selectedChapters.addAll(
        _allChapters
            .where((c) => c.number > maxExisting && !_existingChapters.contains(c.number))
            .map((c) => c.number),
      );
    });
  }

  void _selectLastN(int n) {
    final available = _allChapters.where((c) => !_existingChapters.contains(c.number)).toList()
      ..sort((a, b) => b.number.compareTo(a.number));
    final last = available.take(n).map((c) => c.number).toSet();
    setState(() {
      _selectedChapters.clear();
      _selectedChapters.addAll(last);
    });
  }

  void _updateRangePreview() {
    final from = double.tryParse(_rangeFromController.text);
    final to = double.tryParse(_rangeToController.text);
    if (from == null || to == null) {
      setState(() => _rangePreviewCount = 0);
      return;
    }
    final low = from < to ? from : to;
    final high = from < to ? to : from;
    int count = 0;
    for (final c in _allChapters) {
      if (c.number >= low && c.number <= high && !_existingChapters.contains(c.number)) {
        count++;
      }
    }
    setState(() => _rangePreviewCount = count);
  }

  void _selectRange() {
    final from = double.tryParse(_rangeFromController.text);
    final to = double.tryParse(_rangeToController.text);
    if (from == null || to == null) return;
    final low = from < to ? from : to;
    final high = from < to ? to : from;
    setState(() {
      _selectedChapters.clear();
      for (final c in _allChapters) {
        if (c.number >= low && c.number <= high && !_existingChapters.contains(c.number)) {
          _selectedChapters.add(c.number);
        }
      }
    });
  }

  void _showRangeInputDialog() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx2, setDialogState) {
          int previewCount = 0;
          void updatePreview(String input) {
            final selected = <double>{};
            final parts = input.split(',');
            for (final part in parts) {
              final trimmed = part.trim();
              if (trimmed.contains('-')) {
                final range = trimmed.split('-');
                final start = double.tryParse(range[0].trim());
                final end = double.tryParse(range[1].trim());
                if (start != null && end != null) {
                  for (double i = start; i <= end; i++) {
                    if (_allChapters.any((c) => c.number == i) && !_existingChapters.contains(i)) {
                      selected.add(i);
                    }
                  }
                }
              } else {
                final num = double.tryParse(trimmed);
                if (num != null && _allChapters.any((c) => c.number == num) && !_existingChapters.contains(num)) {
                  selected.add(num);
                }
              }
            }
            setDialogState(() => previewCount = selected.length);
          }

          return AlertDialog(
            title: const Text('Pilih Chapter (Range/Manual)'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Format: 1-10,15,20-25\nChapter yang sudah ada akan dilewati otomatis',
                  style: Theme.of(ctx2).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: controller,
                  decoration: InputDecoration(
                    hintText: '1-10,15,20-25',
                    border: const OutlineInputBorder(),
                    suffixText: previewCount > 0 ? '$previewCount chapter' : null,
                  ),
                  autofocus: true,
                  textInputAction: TextInputAction.done,
                  onChanged: updatePreview,
                  onSubmitted: (v) {
                    _parseAndSelectRange(v, ctx2);
                    Navigator.pop(ctx2);
                  },
                ),
                if (previewCount > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text('$previewCount chapter akan dipilih',
                        style: Theme.of(ctx2).textTheme.bodySmall?.copyWith(color: AppColors.secondary)),
                  ),
              ],
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx2), child: const Text('Batal')),
              FilledButton(
                onPressed: () {
                  _parseAndSelectRange(controller.text, ctx2);
                  Navigator.pop(ctx2);
                },
                child: const Text('Pilih'),
              ),
            ],
          );
        },
      ),
    );
  }

  void _parseAndSelectRange(String input, BuildContext ctx) {
    final selected = <double>{};
    final parts = input.split(',');
    for (final part in parts) {
      final trimmed = part.trim();
      if (trimmed.contains('-')) {
        final range = trimmed.split('-');
        final start = double.tryParse(range[0].trim());
        final end = double.tryParse(range[1].trim());
        if (start != null && end != null) {
          for (double i = start; i <= end; i++) {
            if (_allChapters.any((c) => c.number == i) && !_existingChapters.contains(i)) {
              selected.add(i);
            }
          }
        }
      } else {
        final num = double.tryParse(trimmed);
        if (num != null && _allChapters.any((c) => c.number == num) && !_existingChapters.contains(num)) {
          selected.add(num);
        }
      }
    }
    setState(() {
      if (selected.isNotEmpty) {
        _selectedChapters.clear();
        _selectedChapters.addAll(selected);
      } else {
        ScaffoldMessenger.of(ctx).showSnackBar(
          const SnackBar(content: Text('Tidak ada chapter valid dalam input')),
        );
      }
    });
  }

  void _onChapterTap(int index) {
    if (_filteredChapters.isEmpty) return;
    final chapter = _filteredChapters[index];
    if (_existingChapters.contains(chapter.number)) return;

    setState(() {
      if (_selectedChapters.contains(chapter.number)) {
        _selectedChapters.remove(chapter.number);
        _rangeStart = null;
      } else {
        _selectedChapters.add(chapter.number);
        _rangeStart = chapter.number;
      }
    });
  }

  void _onChapterLongPress(int index) {
    if (_filteredChapters.isEmpty) return;
    final chapter = _filteredChapters[index];
    if (_existingChapters.contains(chapter.number)) return;

    if (_rangeStart != null) {
      final start = _rangeStart!;
      final end = chapter.number;
      final low = start < end ? start : end;
      final high = start < end ? end : start;

      setState(() {
        for (final c in _allChapters) {
          if (c.number >= low && c.number <= high && !_existingChapters.contains(c.number)) {
            _selectedChapters.add(c.number);
          }
        }
        _rangeStart = null;
      });
    } else {
      setState(() {
        _rangeStart = chapter.number;
        _selectedChapters.add(chapter.number);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(_title.isNotEmpty ? _title : 'Detail Series'),
        centerTitle: true,
        actions: [
          IconButton(
            icon: Icon(Icons.filter_list, color: _showRangeSelector ? AppColors.primary : null),
            tooltip: 'Range selector',
            onPressed: () => setState(() => _showRangeSelector = !_showRangeSelector),
          ),
          IconButton(
            icon: Icon(_sortOrder == ChapterSortOrder.ascending
                ? Icons.arrow_upward : Icons.arrow_downward),
            tooltip: 'Urutan chapter',
            onPressed: () {
              setState(() {
                _sortOrder = _sortOrder == ChapterSortOrder.ascending
                    ? ChapterSortOrder.descending
                    : ChapterSortOrder.ascending;
              });
              _applyFilter();
            },
          ),
        ],
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
              : _allChapters.isEmpty
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
                        _buildInfoBar(textTheme),
                        _buildQuickActions(textTheme),
                        if (_showRangeSelector) _buildRangeSelector(textTheme),
                        _buildFilterField(textTheme),
                        Expanded(
                          child: _filteredChapters.isEmpty
                              ? Center(
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.search_off, size: 48, color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                                      const SizedBox(height: AppDimensions.spacingMd),
                                      Text('Tidak ada chapter cocok dengan filter "$_chapterFilter"',
                                          style: textTheme.bodyMedium?.copyWith(color: AppColors.onSurfaceVariant),
                                          textAlign: TextAlign.center),
                                    ],
                                  ),
                                )
                              : ListView.builder(
                                  itemCount: _filteredChapters.length,
                                  itemBuilder: (_, i) => _buildChapterTile(i, textTheme),
                                ),
                        ),
                        if (_selectedChapters.isNotEmpty)
                          _buildBottomBar(textTheme),
                      ],
                    ),
    );
  }

  Widget _buildInfoBar(TextTheme textTheme) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppDimensions.spacingMd, AppDimensions.spacingSm, AppDimensions.spacingMd, 0,
      ),
      child: Row(
        children: [
          Icon(Icons.auto_stories_outlined, size: 16, color: AppColors.primary),
          const SizedBox(width: 6),
          Text('${_allChapters.length} chapter', style: textTheme.bodySmall),
          if (_chapterFilter.isNotEmpty && _filteredChapters.length != _allChapters.length) ...[
            const SizedBox(width: 6),
            Text('(${_filteredChapters.length} difilter)', style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant)),
          ],
          if (_existingChapters.isNotEmpty) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.secondary.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('${_existingChapters.length} sudah ada',
                  style: textTheme.labelSmall?.copyWith(color: AppColors.secondary)),
            ),
          ],
          if (_selectedChapters.isNotEmpty) ...[
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.primary.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('${_selectedChapters.length} dipilih',
                  style: textTheme.labelSmall?.copyWith(color: AppColors.primary)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildQuickActions(TextTheme textTheme) {
    return Column(
      children: [
        if (_showQuickButtons || _selectedChapters.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd, vertical: 4),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  _QuickChip(label: 'Semua', icon: Icons.select_all, onTap: _selectAll),
                  const SizedBox(width: 6),
                  _QuickChip(label: 'None', icon: Icons.deselect, onTap: _deselectAll),
                  const SizedBox(width: 6),
                  _QuickChip(label: 'Balik', icon: Icons.swap_horiz, onTap: _invertSelection),
                  const SizedBox(width: 6),
                  _QuickChip(label: 'Baru', icon: Icons.fiber_new, onTap: _selectNewOnly),
                  const SizedBox(width: 6),
                  _QuickChip(label: 'Lanjutkan', icon: Icons.skip_next, onTap: _selectFromLastSaved),
                  const SizedBox(width: 6),
                  _QuickChip(label: '5', icon: Icons.numbers, onTap: () => _selectLastN(5)),
                  const SizedBox(width: 6),
                  _QuickChip(label: '10', icon: Icons.numbers, onTap: () => _selectLastN(10)),
                  const SizedBox(width: 6),
                  _QuickChip(label: 'Range', icon: Icons.dialpad, onTap: _showRangeInputDialog),
                  const SizedBox(width: 4),
                  IconButton(
                    icon: Icon(_showQuickButtons ? Icons.visibility : Icons.visibility_off,
                        size: 20, color: AppColors.onSurfaceVariant),
                    tooltip: 'Sembunyikan/tampilkan tombol',
                    onPressed: () => setState(() => _showQuickButtons = !_showQuickButtons),
                    visualDensity: VisualDensity.compact,
                  ),
                ],
              ),
            ),
          )
          else
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd, vertical: 4),
              child: SizedBox(
                width: double.infinity,
                child: TextButton.icon(
                  onPressed: () => setState(() => _showQuickButtons = true),
                  icon: const Icon(Icons.expand_more, size: 18),
                  label: const Text('Pilih Chapter Cepat'),
                ),
              ),
            ),
      ],
    );
  }

  Widget _buildRangeSelector(TextTheme textTheme) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd, vertical: 4),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppDimensions.spacingSm),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.compare_arrows, size: 16, color: AppColors.primary),
                  const SizedBox(width: 6),
                  Text('Pilih Range Chapter', style: textTheme.labelSmall?.copyWith(color: AppColors.primary)),
                  const Spacer(),
                  SizedBox(
                    height: 28,
                    child: TextButton(
                      onPressed: () => _showRangeInputDialog(),
                      style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8)),
                      child: Text('Manual', style: textTheme.labelSmall),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _rangeFromController,
                      decoration: InputDecoration(
                        labelText: 'Dari',
                        hintText: '1',
                        border: const OutlineInputBorder(),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                      ),
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.next,
                      onChanged: (_) => _updateRangePreview(),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: Icon(Icons.arrow_forward, size: 16, color: AppColors.onSurfaceVariant),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _rangeToController,
                      decoration: InputDecoration(
                        labelText: 'Ke',
                        hintText: '100',
                        border: const OutlineInputBorder(),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                      ),
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.done,
                      onChanged: (_) => _updateRangePreview(),
                      onSubmitted: (_) {
                        if (_rangePreviewCount > 0) _selectRange();
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 40,
                    child: FilledButton(
                      onPressed: _rangePreviewCount > 0 ? _selectRange : null,
                      child: Text('Pilih${_rangePreviewCount > 0 ? " ($_rangePreviewCount)" : ""}',
                          style: const TextStyle(fontSize: 12)),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFilterField(TextTheme textTheme) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd, vertical: 4),
      child: SizedBox(
        height: 40,
        child: TextField(
          controller: _filterController,
          decoration: InputDecoration(
            hintText: 'Cari chapter...',
            prefixIcon: const Icon(Icons.search, size: 18),
            suffixIcon: _chapterFilter.isNotEmpty
                ? IconButton(
                    icon: const Icon(Icons.clear, size: 18),
                    onPressed: () {
                      _filterController.clear();
                      setState(() => _chapterFilter = '');
                      _applyFilter();
                    },
                  )
                : null,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            isDense: true,
          ),
          onChanged: (v) {
            setState(() => _chapterFilter = v);
            _applyFilter();
          },
        ),
      ),
    );
  }

  Widget _buildChapterTile(int index, TextTheme textTheme) {
    final chapter = _filteredChapters[index];
    final isSelected = _selectedChapters.contains(chapter.number);
    final isExisting = _existingChapters.contains(chapter.number);
    final isRangeStart = _rangeStart == chapter.number;

    return Opacity(
      opacity: isExisting ? 0.55 : 1.0,
      child: Card(
        margin: const EdgeInsets.symmetric(
          horizontal: AppDimensions.spacingMd,
          vertical: 2,
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
          onTap: isExisting ? null : () => _onChapterTap(index),
          onLongPress: isExisting ? null : () => _onChapterLongPress(index),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Container(
                  width: 24, height: 24,
                  decoration: BoxDecoration(
                    color: isExisting
                        ? AppColors.secondary.withValues(alpha: 0.2)
                        : isSelected || isRangeStart
                            ? AppColors.primary.withValues(alpha: 0.2)
                            : AppColors.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(
                      color: isExisting
                          ? AppColors.secondary.withValues(alpha: 0.4)
                          : isSelected || isRangeStart
                              ? AppColors.primary
                              : AppColors.outlineVariant,
                      width: isSelected || isRangeStart ? 2 : 1,
                    ),
                  ),
                  child: Icon(
                    isExisting
                        ? Icons.check_circle_outline
                        : isSelected
                            ? Icons.check
                            : Icons.add,
                    size: 14,
                    color: isExisting
                        ? AppColors.secondary
                        : isSelected || isRangeStart
                            ? AppColors.primary
                            : AppColors.onSurfaceVariant,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Chapter ${chapter.label}',
                          style: textTheme.bodyMedium?.copyWith(
                            fontWeight: isSelected || isRangeStart ? FontWeight.w600 : FontWeight.normal,
                          )),
                      if (isExisting)
                        Text('Sudah ada di folder',
                            style: textTheme.labelSmall?.copyWith(color: AppColors.secondary)),
                    ],
                  ),
                ),
                if (isRangeStart)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppColors.primary.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text('Start', style: textTheme.labelSmall?.copyWith(color: AppColors.primary)),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBottomBar(TextTheme textTheme) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        AppDimensions.spacingMd, AppDimensions.spacingSm, AppDimensions.spacingMd, AppDimensions.spacingMd,
      ),
      decoration: BoxDecoration(
        color: AppColors.surfaceContainerLow,
        border: Border(
          top: BorderSide(color: AppColors.outlineVariant.withValues(alpha: 0.5)),
        ),
      ),
      child: SafeArea(
        top: false,
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
    );
  }
}

class _QuickChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;
  const _QuickChip({required this.label, required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return ActionChip(
      label: Text(label, style: const TextStyle(fontSize: 12)),
      avatar: Icon(icon, size: 14),
      onPressed: onTap,
      visualDensity: VisualDensity.compact,
      padding: const EdgeInsets.symmetric(horizontal: 4),
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}