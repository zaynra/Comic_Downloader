import 'dart:async';
import 'package:shared_preferences/shared_preferences.dart';
import '../../domain/models/chapter.dart';
import '../../domain/models/download_job.dart';
import '../services/download_engine.dart';
import '../services/notification_service.dart';
import '../services/foreground_service.dart';

class DownloadRepository {
  final List<DownloadJob> _jobs = [];
  final _jobListeners = <String, List<void Function(DownloadJob)>>{};
  final DownloadEngine _engine = DownloadEngine();
  StreamSubscription<Object>? _engineSubscription;
  bool _engineStarted = false;

  List<DownloadJob> get jobs => List.unmodifiable(_jobs);

  void addListener(String jobId, void Function(DownloadJob) listener) {
    _jobListeners.putIfAbsent(jobId, () => []).add(listener);
  }

  void removeListener(String jobId, void Function(DownloadJob) listener) {
    _jobListeners[jobId]?.remove(listener);
  }

  void _notify(DownloadJob job) {
    for (final listener in _jobListeners[job.id] ?? []) {
      listener(job);
    }
  }

  Future<void> _ensureEngineStarted() async {
    if (_engineStarted) return;
    _engineStarted = true;
    await _engine.start();

    _engineSubscription = _engine.updates.listen((update) {
      if (update is EngineUpdate) {
        _handleEngineUpdate(update);
      } else if (update is EngineCompletion) {
        _handleEngineCompletion(update);
      }
    });
  }

  void _handleEngineUpdate(EngineUpdate update) {
    final job = getJob(update.jobId);
    if (job == null || update.chapterIndex >= job.chapters.length) return;

    final chapter = job.chapters[update.chapterIndex];
    chapter.status = update.status;
    chapter.progressPages = update.progressPages;
    chapter.totalPages = update.totalPages;
    if (update.pdfPath != null) chapter.pdfPath = update.pdfPath;

    _notify(job);

    final notif = NotificationService.instance;
    notif.showProgress(
      id: int.tryParse(job.id) ?? 0,
      title: job.seriesTitle,
      body: 'Chapter ${chapter.label}: ${update.progressPages}/${update.totalPages} halaman',
      progress: job.completedChapters + job.failedChapters + update.chapterIndex,
      maxProgress: job.totalChapters,
    );

    ForegroundServiceManager.instance.updateNotification(
      title: job.seriesTitle,
      content: 'Chapter ${chapter.label} (${update.progressPages}/${update.totalPages})',
      progress: job.completedChapters + job.failedChapters + update.chapterIndex,
      maxProgress: job.totalChapters,
    );
  }

  void _handleEngineCompletion(EngineCompletion completion) {
    final job = getJob(completion.jobId);
    if (job == null) return;

    job.completedAt = DateTime.now();
    _notify(job);

    final notif = NotificationService.instance;
    if (completion.failedChapters > 0) {
      notif.showError(
        id: int.tryParse(job.id) ?? 0,
        title: job.seriesTitle,
        body: '${completion.completedChapters} selesai, ${completion.failedChapters} gagal',
      );
    } else {
      notif.showCompletion(
        id: int.tryParse(job.id) ?? 0,
        title: job.seriesTitle,
        body: '${completion.completedChapters} chapter berhasil diunduh',
      );
    }

    final anyActive = _jobs.any((j) => !j.isDone);
    if (!anyActive) {
      ForegroundServiceManager.instance.stop();
    }
  }

  Future<DownloadJob> createJob({
    required String seriesUrl,
    required String seriesTitle,
    required String adapterName,
    required List<Chapter> chapters,
    required String outputFolder,
  }) async {
    await _ensureEngineStarted();

    final job = DownloadJob(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      seriesTitle: seriesTitle,
      seriesUrl: seriesUrl,
      adapterName: adapterName,
      chapters: chapters,
      outputFolder: outputFolder,
    );

    _jobs.add(job);
    _notify(job);
    return job;
  }

  Future<void> startJob(DownloadJob job) async {
    job.startedAt = DateTime.now();
    job.isPaused = false;
    _notify(job);

    await ForegroundServiceManager.instance.start();

    _engine.sendCommand(EngineMessage(
      command: EngineCommand.startJob,
      jobId: job.id,
      data: {
        'seriesUrl': job.seriesUrl,
        'seriesTitle': job.seriesTitle,
        'adapterName': job.adapterName,
        'chapterNumbers': job.chapters.map((c) => c.number).toList(),
        'chapterUrls': job.chapters.map((c) => c.url).toList(),
        'chapterLabels': job.chapters.map((c) => c.label).toList(),
        'outputFolder': job.outputFolder,
      },
    ));
  }

  void cancelJob(String jobId) {
    final job = getJob(jobId);
    if (job == null) return;
    job.isCancelled = true;
    _notify(job);
    _engine.sendCommand(EngineMessage(
      command: EngineCommand.cancelJob,
      jobId: jobId,
    ));
  }

  void pauseJob(String jobId) {
    final job = getJob(jobId);
    if (job == null) return;
    job.isPaused = true;
    _notify(job);
    _engine.sendCommand(EngineMessage(
      command: EngineCommand.pauseJob,
      jobId: jobId,
    ));
  }

  void resumeJob(String jobId) {
    final job = getJob(jobId);
    if (job == null) return;
    job.isPaused = false;
    _notify(job);
    _engine.sendCommand(EngineMessage(
      command: EngineCommand.resumeJob,
      jobId: jobId,
    ));
  }

  void removeJob(String jobId) {
    _jobs.removeWhere((j) => j.id == jobId);
  }

  DownloadJob? getJob(String jobId) {
    try {
      return _jobs.firstWhere((j) => j.id == jobId);
    } catch (_) {
      return null;
    }
  }

  Future<String> getDefaultOutputFolder() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('output_folder') ?? '';
  }

  Future<void> setDefaultOutputFolder(String path) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('output_folder', path);
  }

  void dispose() {
    _engineSubscription?.cancel();
    _engine.dispose();
  }
}
