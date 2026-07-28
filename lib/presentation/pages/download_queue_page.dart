import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../domain/models/chapter.dart';
import '../../domain/models/download_job.dart';
import '../providers/download_provider.dart';

class DownloadQueuePage extends ConsumerWidget {
  const DownloadQueuePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final textTheme = Theme.of(context).textTheme;
    final jobs = ref.watch(downloadJobsProvider).valueOrNull ?? [];

    return Scaffold(
      appBar: AppBar(
        title: const Text('Antrian Unduhan'),
        centerTitle: true,
      ),
      body: jobs.isEmpty
          ? Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.download_outlined, size: 64,
                      color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                  const SizedBox(height: AppDimensions.spacingMd),
                  Text('Belum ada unduhan',
                      style: textTheme.bodyLarge?.copyWith(color: AppColors.onSurfaceVariant)),
                ],
              ),
            )
          : ListView.builder(
              padding: const EdgeInsets.all(AppDimensions.spacingMd),
              itemCount: jobs.length,
              itemBuilder: (_, i) {
                final job = jobs[i];
                final activeChapters = job.chapters
                    .where((c) => c.status == ChapterStatus.downloading)
                    .toList();
                final progress = job.totalChapters > 0
                    ? (job.completedChapters / job.totalChapters)
                    : 0.0;

                return Card(
                  margin: const EdgeInsets.only(bottom: AppDimensions.spacingMd),
                  child: Padding(
                    padding: const EdgeInsets.all(AppDimensions.spacingMd),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(job.seriesTitle,
                                  style: textTheme.titleMedium,
                                  maxLines: 1, overflow: TextOverflow.ellipsis),
                            ),
                            const SizedBox(width: 8),
                            _StatusChip(job: job, textTheme: textTheme),
                          ],
                        ),
                        const SizedBox(height: AppDimensions.spacingSm),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                          child: LinearProgressIndicator(
                            value: progress, minHeight: 4,
                            backgroundColor: AppColors.surfaceContainerHigh,
                          ),
                        ),
                        const SizedBox(height: AppDimensions.spacingSm),
                        Text('${job.completedChapters}/${job.totalChapters} chapter selesai',
                            style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                        if (activeChapters.isNotEmpty) ...[
                          const SizedBox(height: AppDimensions.spacingXs),
                          Text('Downloading: Chapter ${activeChapters.first.label} '
                              '(${activeChapters.first.progressPages}/${activeChapters.first.totalPages})',
                              style: textTheme.bodySmall?.copyWith(color: AppColors.secondary)),
                        ],
                        if (job.failedChapters > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: AppDimensions.spacingXs),
                            child: Text('${job.failedChapters} chapter gagal',
                                style: textTheme.bodySmall?.copyWith(color: AppColors.error)),
                          ),
                        const SizedBox(height: AppDimensions.spacingSm),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            if (job.isDone) ...[
                              _QueueButton(
                                icon: Icons.visibility_outlined, tooltip: 'Preview',
                                onPressed: () {
                                  final completed = job.chapters
                                      .where((c) => c.status == ChapterStatus.completed && c.pdfPath != null)
                                      .toList();
                                  if (completed.isNotEmpty) {
                                    context.push('/preview/${Uri.encodeComponent(completed.first.pdfPath!)}?title=${Uri.encodeComponent(job.seriesTitle)}');
                                  }
                                },
                              ),
                              _QueueButton(
                                icon: Icons.refresh, tooltip: 'Download Ulang',
                                onPressed: () {
                                  final repo = ref.read(downloadRepositoryProvider);
                                  for (final ch in job.chapters) {
                                    ch.status = ChapterStatus.pending;
                                    ch.pdfPath = null;
                                  }
                                  job.isCancelled = false;
                                  job.isPaused = false;
                                  job.completedAt = null;
                                  repo.startJob(job);
                                },
                              ),
                              _QueueButton(
                                icon: Icons.delete_outline, tooltip: 'Hapus',
                                onPressed: () => ref.read(downloadRepositoryProvider).removeJob(job.id),
                              ),
                            ] else ...[
                              _QueueButton(
                                icon: job.isPaused ? Icons.play_arrow : Icons.pause,
                                tooltip: job.isPaused ? 'Lanjutkan' : 'Jeda',
                                onPressed: () {
                                  final repo = ref.read(downloadRepositoryProvider);
                                  job.isPaused ? repo.resumeJob(job.id) : repo.pauseJob(job.id);
                                },
                              ),
                              _QueueButton(
                                icon: Icons.stop, tooltip: 'Hentikan',
                                onPressed: () => ref.read(downloadRepositoryProvider).cancelJob(job.id),
                              ),
                            ],
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class _QueueButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  const _QueueButton({required this.icon, required this.tooltip, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 40, height: 40,
      child: IconButton(
        icon: Icon(icon, size: 20),
        tooltip: tooltip,
        onPressed: onPressed,
        padding: EdgeInsets.zero,
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final DownloadJob job;
  final TextTheme textTheme;
  const _StatusChip({required this.job, required this.textTheme});

  @override
  Widget build(BuildContext context) {
    String label;
    Color color;
    if (job.isDone) {
      label = job.failedChapters > 0 ? 'Selesai (${job.failedChapters} error)' : 'Selesai';
      color = job.failedChapters > 0 ? AppColors.error : AppColors.secondary;
    } else if (job.isPaused) {
      label = 'Dihentikan';
      color = AppColors.tertiary;
    } else {
      label = 'Downloading';
      color = AppColors.primary;
    }
    return Chip(
      label: Text(label, style: textTheme.labelSmall?.copyWith(color: color)),
      backgroundColor: color.withValues(alpha: 0.15),
      side: BorderSide.none,
      visualDensity: VisualDensity.compact,
      padding: const EdgeInsets.symmetric(horizontal: 4),
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}
