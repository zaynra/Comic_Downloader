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
    final activeJobs = jobs.where((j) => !j.isDone).toList();
    final doneJobs = jobs.where((j) => j.isDone).toList();
    final failedJobs = doneJobs.where((j) => j.failedChapters > 0).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Antrian Unduhan'),
        centerTitle: true,
        actions: [
          if (doneJobs.isNotEmpty)
            PopupMenuButton<String>(
              icon: const Icon(Icons.more_vert),
              onSelected: (v) {
                final repo = ref.read(downloadRepositoryProvider);
                switch (v) {
                  case 'retry_failed':
                    for (final job in failedJobs) {
                      for (final ch in job.chapters) {
                        if (ch.status == ChapterStatus.failed) {
                          ch.status = ChapterStatus.pending;
                          ch.pdfPath = null;
                        }
                      }
                      if (job.chapters.any((c) => c.status == ChapterStatus.pending)) {
                        job.isCancelled = false;
                        job.isPaused = false;
                        job.completedAt = null;
                        repo.startJob(job);
                      }
                    }
                  case 'clear_done':
                    for (final job in doneJobs) {
                      repo.removeJob(job.id);
                    }
                  case 'clear_all':
                    for (final job in jobs) {
                      repo.removeJob(job.id);
                    }
                }
              },
              itemBuilder: (_) => [
                if (failedJobs.isNotEmpty)
                  const PopupMenuItem(value: 'retry_failed', child: Text('Retry All Failed')),
                const PopupMenuItem(value: 'clear_done', child: Text('Clear Completed')),
                const PopupMenuItem(value: 'clear_all', child: Text('Clear All')),
              ],
            ),
        ],
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
                  const SizedBox(height: AppDimensions.spacingSm),
                  Text('Buka komik dan download chapter untuk mulai',
                      style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                ],
              ),
            )
          : DefaultTabController(
              length: 2,
              child: Column(
                children: [
                  TabBar(
                    tabs: [
                      Tab(text: 'Berjalan (${activeJobs.length})'),
                      Tab(text: 'Selesai (${doneJobs.length})'),
                    ],
                    labelColor: AppColors.primary,
                    unselectedLabelColor: AppColors.onSurfaceVariant,
                    indicatorColor: AppColors.primary,
                  ),
                  Expanded(
                    child: TabBarView(
                      children: [
                        activeJobs.isEmpty
                            ? Center(
                                child: Padding(
                                  padding: const EdgeInsets.all(AppDimensions.spacingLg),
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.check_circle_outline, size: 48,
                                          color: AppColors.secondary.withValues(alpha: 0.5)),
                                      const SizedBox(height: AppDimensions.spacingMd),
                                      Text('Tidak ada unduhan aktif',
                                          style: textTheme.bodyMedium?.copyWith(color: AppColors.onSurfaceVariant)),
                                    ],
                                  ),
                                ),
                              )
                            : ListView.builder(
                                padding: const EdgeInsets.all(AppDimensions.spacingMd),
                                itemCount: activeJobs.length,
                                itemBuilder: (_, i) => _JobCard(job: activeJobs[i], textTheme: textTheme),
                              ),
                        doneJobs.isEmpty
                            ? Center(
                                child: Padding(
                                  padding: const EdgeInsets.all(AppDimensions.spacingLg),
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.download_done_outlined, size: 48,
                                          color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                                      const SizedBox(height: AppDimensions.spacingMd),
                                      Text('Belum ada unduhan selesai',
                                          style: textTheme.bodyMedium?.copyWith(color: AppColors.onSurfaceVariant)),
                                    ],
                                  ),
                                ),
                              )
                            : ListView.builder(
                                padding: const EdgeInsets.all(AppDimensions.spacingMd),
                                itemCount: doneJobs.length,
                                itemBuilder: (_, i) => _JobCard(job: doneJobs[i], textTheme: textTheme),
                              ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

class _JobCard extends ConsumerStatefulWidget {
  final DownloadJob job;
  final TextTheme textTheme;
  const _JobCard({required this.job, required this.textTheme});

  @override
  ConsumerState<_JobCard> createState() => _JobCardState();
}

class _JobCardState extends ConsumerState<_JobCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final job = widget.job;
    final textTheme = widget.textTheme;
    final progress = job.totalChapters > 0 ? (job.completedChapters / job.totalChapters) : 0.0;
    final chapters = job.chapters;

    return Dismissible(
      key: ValueKey('job_${job.id}'),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        margin: const EdgeInsets.only(bottom: AppDimensions.spacingMd),
        decoration: BoxDecoration(
          color: AppColors.error,
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
        child: const Icon(Icons.delete_outline, color: Colors.white),
      ),
      confirmDismiss: (_) => showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Hapus Job?'),
          content: Text('Hapus job "${job.seriesTitle}"?'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Batal')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Hapus')),
          ],
        ),
      ),
      onDismissed: (_) => ref.read(downloadRepositoryProvider).removeJob(job.id),
      child: Card(
        margin: const EdgeInsets.only(bottom: AppDimensions.spacingMd),
        child: Column(
          children: [
            InkWell(
              borderRadius: _expanded
                  ? const BorderRadius.vertical(top: Radius.circular(AppDimensions.radiusSm))
                  : BorderRadius.circular(AppDimensions.radiusSm),
              onTap: () => setState(() => _expanded = !_expanded),
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
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: progress, minHeight: 4,
                        backgroundColor: AppColors.surfaceContainerHigh,
                      ),
                    ),
                    const SizedBox(height: AppDimensions.spacingSm),
                    Row(
                      children: [
                        Text('${job.completedChapters}/${job.totalChapters} chapter',
                            style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                        const Spacer(),
                        if (job.failedChapters > 0)
                          Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: Text('${job.failedChapters} gagal',
                                style: textTheme.bodySmall?.copyWith(color: AppColors.error)),
                          ),
                        Text(job.isDone
                            ? (job.completedAt != null ? 'Selesai ${_formatTime(job.completedAt!)}' : 'Selesai')
                            : job.isPaused ? 'Dihentikan' : 'Berjalan',
                            style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                        const SizedBox(width: 4),
                        Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 18),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            if (_expanded) ...[
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.all(AppDimensions.spacingSm),
                child: Column(
                  children: chapters.map((ch) => _buildChapterRow(ch, textTheme)).toList(),
                ),
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppDimensions.spacingSm, 0, AppDimensions.spacingSm, AppDimensions.spacingSm,
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    if (job.isDone) ...[
                      _QueueButton(
                        icon: Icons.visibility_outlined, tooltip: 'Preview',
                        onPressed: _navigatePreview,
                      ),
                      _QueueButton(
                        icon: Icons.refresh, tooltip: 'Download Ulang',
                        onPressed: _retryJob,
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
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _navigatePreview() {
    final completed = widget.job.chapters
        .where((c) => c.status == ChapterStatus.completed && c.pdfPath != null)
        .toList();
    if (completed.isNotEmpty) {
      context.push('/preview/${Uri.encodeComponent(completed.first.pdfPath!)}'
          '?title=${Uri.encodeComponent(widget.job.seriesTitle)}');
    }
  }

  void _retryJob() {
    final repo = ref.read(downloadRepositoryProvider);
    final job = widget.job;
    final anyPending = job.chapters.any((c) => c.status == ChapterStatus.failed || c.status == ChapterStatus.pending);
    if (!anyPending) {
      for (final ch in job.chapters) {
        ch.status = ChapterStatus.pending;
        ch.pdfPath = null;
      }
    }
    job.isCancelled = false;
    job.isPaused = false;
    job.completedAt = null;
    repo.startJob(job);
  }

  Widget _buildChapterRow(Chapter ch, TextTheme textTheme) {
    final statusIcon = switch (ch.status) {
      ChapterStatus.completed => Icons.check_circle,
      ChapterStatus.failed => Icons.error,
      ChapterStatus.downloading => Icons.downloading,
      _ => Icons.hourglass_bottom,
    };
    final statusColor = switch (ch.status) {
      ChapterStatus.completed => AppColors.secondary,
      ChapterStatus.failed => AppColors.error,
      ChapterStatus.downloading => AppColors.primary,
      _ => AppColors.onSurfaceVariant,
    };

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Icon(statusIcon, size: 14, color: statusColor),
          const SizedBox(width: 8),
          Expanded(
            child: Text('Chapter ${ch.label}',
                style: textTheme.bodySmall),
          ),
          if (ch.progressPages > 0 && ch.totalPages > 0)
            Text('${ch.progressPages}/${ch.totalPages}',
                style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant)),
        ],
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'baru saja';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m lalu';
    if (diff.inHours < 24) return '${diff.inHours}j lalu';
    return '${diff.inDays}h lalu';
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