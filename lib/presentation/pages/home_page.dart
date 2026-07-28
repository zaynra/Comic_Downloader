import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../data/datasources/adapter_resolver.dart';
import '../../domain/models/chapter.dart';
import '../../domain/models/download_job.dart';
import '../providers/download_provider.dart';

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _urlController = TextEditingController();
  final _urlFocusNode = FocusNode();
  List<String> _recentUrls = [];
  bool _isUrlValid = true;
  String? _urlErrorText;

  @override
  void initState() {
    super.initState();
    _loadRecentUrls();
  }

  @override
  void dispose() {
    _urlController.dispose();
    _urlFocusNode.dispose();
    super.dispose();
  }

  Future<void> _loadRecentUrls() async {
    final prefs = await SharedPreferences.getInstance();
    final urls = prefs.getStringList('recent_urls') ?? [];
    if (mounted) setState(() => _recentUrls = urls);
  }

  Future<void> _saveRecentUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    final urls = prefs.getStringList('recent_urls') ?? [];
    urls.remove(url);
    urls.insert(0, url);
    if (urls.length > 10) urls.removeRange(10, urls.length);
    await prefs.setStringList('recent_urls', urls);
    if (mounted) setState(() => _recentUrls = urls);
  }

  Future<void> _clearRecentUrls() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList('recent_urls', []);
    if (mounted) setState(() => _recentUrls = []);
  }

  void _validateUrl(String text) {
    if (text.isEmpty) {
      setState(() { _isUrlValid = true; _urlErrorText = null; });
      return;
    }
    final uri = Uri.tryParse(text);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) {
      setState(() { _isUrlValid = false; _urlErrorText = 'URL tidak valid. Masukkan URL lengkap (https://...)'; });
    } else {
      try {
        resolveAdapter(text);
        setState(() { _isUrlValid = true; _urlErrorText = null; });
      } catch (_) {
        setState(() { _isUrlValid = false; _urlErrorText = 'Situs ini belum didukung oleh adapter yang tersedia'; });
      }
    }
  }

  Future<void> _pasteUrl() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (data?.text != null && data!.text!.isNotEmpty) {
      _urlController.text = data.text!;
      _validateUrl(data.text!);
      _submitUrl(data.text!);
    }
  }

  Future<void> _submitUrl(String url) async {
    final trimmed = url.trim();
    if (trimmed.isEmpty) return;
    try {
      resolveAdapter(trimmed);
      await _saveRecentUrl(trimmed);
      if (context.mounted) {
        context.push('/series/${Uri.encodeComponent(trimmed)}');
      }
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('URL tidak didukung oleh adapter manapun')),
        );
      }
    }
  }

  String _getActiveChapterLabel(DownloadJob job) {
    for (final ch in job.chapters) {
      if (ch.status == ChapterStatus.downloading) return 'Ch. ${ch.label}';
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final activeJobs = ref.watch(activeDownloadJobsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Comic Downloader'),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.push('/settings'),
          ),
        ],
      ),
      body: CustomScrollView(
        slivers: [
          SliverPadding(
            padding: const EdgeInsets.all(AppDimensions.spacingMd),
            sliver: SliverToBoxAdapter(
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppDimensions.spacingMd),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.link, color: AppColors.primary, size: 20),
                          const SizedBox(width: 8),
                          Text('Buka Series atau Chapter', style: textTheme.titleSmall),
                        ],
                      ),
                      const SizedBox(height: AppDimensions.spacingSm),
                      TextField(
                        controller: _urlController,
                        focusNode: _urlFocusNode,
                        decoration: InputDecoration(
                          hintText: 'https://...',
                          prefixIcon: const Icon(Icons.link),
                          suffixIcon: IconButton(
                            icon: const Icon(Icons.paste_outlined),
                            tooltip: 'Tempel dari clipboard',
                            onPressed: _pasteUrl,
                          ),
                          border: const OutlineInputBorder(),
                          errorText: _urlErrorText,
                          errorMaxLines: 2,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                        ),
                        textInputAction: TextInputAction.go,
                        onChanged: _validateUrl,
                        onSubmitted: (url) => _submitUrl(url),
                      ),
                      const SizedBox(height: AppDimensions.spacingSm),
                      SizedBox(
                        height: 44,
                        child: FilledButton.icon(
                          onPressed: (_urlController.text.trim().isNotEmpty && _isUrlValid)
                              ? () => _submitUrl(_urlController.text.trim())
                              : null,
                          icon: const Icon(Icons.arrow_forward, size: 18),
                          label: const Text('Buka Series / Chapter'),
                        ),
                      ),
                      if (_recentUrls.isNotEmpty) ...[
                        const SizedBox(height: AppDimensions.spacingMd),
                        Row(
                          children: [
                            Text('Baru Dilihat', style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant)),
                            const Spacer(),
                            IconButton(
                              icon: const Icon(Icons.delete_sweep_outlined, size: 18),
                              tooltip: 'Hapus semua riwayat',
                              onPressed: _clearRecentUrls,
                              visualDensity: VisualDensity.compact,
                              padding: EdgeInsets.zero,
                              constraints: const BoxConstraints(),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: _recentUrls.take(5).map((url) {
                            final host = Uri.tryParse(url)?.host.replaceFirst('www.', '') ?? url;
                            return ActionChip(
                              label: Text(host, style: const TextStyle(fontSize: 11), overflow: TextOverflow.ellipsis),
                              avatar: const Icon(Icons.history, size: 14),
                              tooltip: url,
                              onPressed: () => context.push('/series/${Uri.encodeComponent(url)}'),
                              visualDensity: VisualDensity.compact,
                              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              padding: const EdgeInsets.symmetric(horizontal: 4),
                            );
                          }).toList(),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd),
              child: Row(
                children: [
                  Icon(Icons.download_outlined, color: AppColors.primary, size: 20),
                  const SizedBox(width: 8),
                  Text('Antrian Aktif', style: textTheme.titleSmall),
                  if (activeJobs.isNotEmpty) ...[
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text('${activeJobs.length}',
                          style: textTheme.labelSmall?.copyWith(color: AppColors.primary)),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: AppDimensions.spacingSm)),
          if (activeJobs.isEmpty)
            SliverFillRemaining(
              hasScrollBody: false,
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(AppDimensions.spacingLg),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.download_outlined, size: 72,
                          color: AppColors.onSurfaceVariant.withValues(alpha: 0.3)),
                      const SizedBox(height: AppDimensions.spacingLg),
                      Text('Belum ada unduhan',
                          style: textTheme.titleMedium?.copyWith(color: AppColors.onSurfaceVariant)),
                      const SizedBox(height: AppDimensions.spacingSm),
                      Text('Tempel URL komik di atas atau\ncari komik melalui ikon search',
                          style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant),
                          textAlign: TextAlign.center),
                      const SizedBox(height: AppDimensions.spacingLg),
                      FilledButton.icon(
                        onPressed: () => context.push('/search'),
                        icon: const Icon(Icons.search, size: 18),
                        label: const Text('Cari Komik'),
                      ),
                    ],
                  ),
                ),
              ),
            )
          else
            SliverList(
              delegate: SliverChildBuilderDelegate(
                (_, i) {
                  final job = activeJobs[i];
                  return _ActiveJobCard(job: job, activeChapterLabel: _getActiveChapterLabel(job), textTheme: textTheme);
                },
                childCount: activeJobs.length,
              ),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => context.push('/search'),
        tooltip: 'Cari Komik',
        child: const Icon(Icons.search),
      ),
    );
  }
}

class _ActiveJobCard extends ConsumerWidget {
  final DownloadJob job;
  final String activeChapterLabel;
  final TextTheme textTheme;
  const _ActiveJobCard({required this.job, required this.activeChapterLabel, required this.textTheme});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progress = job.totalChapters > 0 ? (job.completedChapters / job.totalChapters) : 0.0;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppDimensions.spacingMd, vertical: 2),
      child: Card(
        child: InkWell(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
          onTap: () => context.push('/queue'),
          child: Padding(
            padding: const EdgeInsets.all(AppDimensions.spacingMd),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.auto_stories_outlined, color: AppColors.primary, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(job.seriesTitle,
                          maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w500)),
                    ),
                    Chip(
                      label: Text(
                        job.isPaused ? 'Jeda' : '${job.completedChapters}/${job.totalChapters}',
                        style: textTheme.labelSmall?.copyWith(
                          color: job.isPaused ? AppColors.tertiary : AppColors.primary,
                        ),
                      ),
                      backgroundColor: (job.isPaused ? AppColors.tertiary : AppColors.primary).withValues(alpha: 0.12),
                      side: BorderSide.none,
                      visualDensity: VisualDensity.compact,
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: progress, minHeight: 3,
                    backgroundColor: AppColors.surfaceContainerHigh,
                    color: job.isPaused ? AppColors.tertiary : AppColors.primary,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Text(
                      job.isPaused
                          ? 'Dihentikan sementara'
                          : activeChapterLabel.isNotEmpty
                              ? 'Mengunduh $activeChapterLabel...'
                              : 'Mengunduh...',
                      style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant),
                    ),
                    const Spacer(),
                    Icon(Icons.chevron_right, size: 18, color: AppColors.onSurfaceVariant),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}