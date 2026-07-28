import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../data/datasources/adapter_resolver.dart';
import '../providers/download_provider.dart';

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _urlController = TextEditingController();

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _pasteUrl() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (data?.text != null && data!.text!.isNotEmpty) {
      _urlController.text = data.text!;
      _submitUrl(data.text!);
    }
  }

  Future<void> _submitUrl(String url) async {
    if (url.trim().isEmpty) return;
    try {
      resolveAdapter(url);
      if (context.mounted) {
        context.push('/series/${Uri.encodeComponent(url.trim())}');
      }
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('URL tidak didukung oleh adapter manapun')),
        );
      }
    }
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
      body: Padding(
        padding: const EdgeInsets.all(AppDimensions.spacingMd),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(AppDimensions.spacingMd),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.link, color: AppColors.primary, size: 20),
                        const SizedBox(width: 8),
                        Text('Tempel URL', style: textTheme.titleSmall),
                      ],
                    ),
                    const SizedBox(height: AppDimensions.spacingSm),
                    TextField(
                      controller: _urlController,
                      decoration: InputDecoration(
                        hintText: 'https://...',
                        prefixIcon: const Icon(Icons.link),
                        suffixIcon: IconButton(
                          icon: const Icon(Icons.paste_outlined),
                          tooltip: 'Tempel dari clipboard',
                          onPressed: _pasteUrl,
                        ),
                        border: const OutlineInputBorder(),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                      ),
                      textInputAction: TextInputAction.go,
                      onSubmitted: (url) => _submitUrl(url),
                    ),
                    const SizedBox(height: AppDimensions.spacingSm),
                    SizedBox(
                      height: 44,
                      child: FilledButton.icon(
                        onPressed: () {
                          if (_urlController.text.trim().isNotEmpty) {
                            _submitUrl(_urlController.text.trim());
                          }
                        },
                        icon: const Icon(Icons.arrow_forward, size: 18),
                        label: const Text('Buka Series / Chapter'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppDimensions.spacingLg),
            Row(
              children: [
                Icon(Icons.download_outlined, color: AppColors.primary, size: 20),
                const SizedBox(width: 8),
                Text('Antrian Aktif', style: textTheme.titleSmall),
              ],
            ),
            const SizedBox(height: AppDimensions.spacingSm),
            Expanded(
              child: activeJobs.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.download_outlined,
                            size: 64,
                            color: AppColors.onSurfaceVariant.withValues(alpha: 0.4),
                          ),
                          const SizedBox(height: AppDimensions.spacingMd),
                          Text(
                            'Belum ada unduhan',
                            style: textTheme.bodyLarge?.copyWith(
                              color: AppColors.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    )
                  : ListView.builder(
                      itemCount: activeJobs.length,
                      itemBuilder: (_, i) {
                        final job = activeJobs[i];
                        return Card(
                          margin: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
                          child: ListTile(
                            leading: const Icon(Icons.auto_stories_outlined, color: AppColors.primary),
                            title: Text(job.seriesTitle, maxLines: 1, overflow: TextOverflow.ellipsis),
                            subtitle: Text(
                              '${job.completedChapters}/${job.totalChapters} chapter',
                              style: textTheme.bodySmall,
                            ),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: () => context.push('/queue'),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => context.push('/search'),
        tooltip: 'Cari Komik',
        child: const Icon(Icons.search),
      ),
    );
  }
}
