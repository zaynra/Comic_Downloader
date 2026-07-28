import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'package:path/path.dart' as p;
import '../../domain/models/chapter.dart';
import '../datasources/adapter_resolver.dart';
import '../datasources/metadata_helper.dart';
import '../datasources/pdf_converter.dart';
import '../datasources/remote_data_source.dart';
import '../../core/utils/chapter_format.dart';

enum EngineCommand { startJob, cancelJob, pauseJob, resumeJob }

class EngineMessage {
  final EngineCommand command;
  final String jobId;
  final Map<String, dynamic>? data;

  const EngineMessage({
    required this.command,
    required this.jobId,
    this.data,
  });
}

class EngineUpdate {
  final String jobId;
  final int chapterIndex;
  final ChapterStatus status;
  final int progressPages;
  final int totalPages;
  final String? pdfPath;
  final String? error;

  const EngineUpdate({
    required this.jobId,
    required this.chapterIndex,
    required this.status,
    this.progressPages = 0,
    this.totalPages = 0,
    this.pdfPath,
    this.error,
  });
}

class EngineCompletion {
  final String jobId;
  final bool success;
  final int completedChapters;
  final int failedChapters;

  const EngineCompletion({
    required this.jobId,
    required this.success,
    required this.completedChapters,
    required this.failedChapters,
  });
}

class DownloadEngine {
  Isolate? _isolate;
  SendPort? _sendPort;
  final ReceivePort _receivePort = ReceivePort();
  final StreamController<Object> _updateController = StreamController<Object>.broadcast();
  bool _initialized = false;

  Stream<Object> get updates => _updateController.stream;

  Future<void> start() async {
    if (_initialized) return;
    _initialized = true;

    final receivePort = ReceivePort();
    _isolate = await Isolate.spawn(
      _downloadIsolateEntry,
      receivePort.sendPort,
    );

    _sendPort = await receivePort.first as SendPort;
    _sendPort!.send(_receivePort.sendPort);

    _receivePort.listen((message) {
      _updateController.add(message);
    });
  }

  void sendCommand(EngineMessage message) {
    _sendPort?.send(message);
  }

  void dispose() {
    _isolate?.kill(priority: Isolate.immediate);
    _receivePort.close();
    _updateController.close();
  }

  @pragma('vm:entry-point')
  static void _downloadIsolateEntry(SendPort sendPort) async {
    final commandPort = ReceivePort();
    sendPort.send(commandPort.sendPort);

    final Map<String, _JobState> jobs = {};

    await for (final message in commandPort) {
      if (message is SendPort) continue;

      if (message is EngineMessage) {
        switch (message.command) {
          case EngineCommand.startJob:
            _runJob(sendPort, commandPort, message, jobs);
          case EngineCommand.cancelJob:
            final state = jobs[message.jobId];
            if (state != null) state.isCancelled = true;
          case EngineCommand.pauseJob:
            final state = jobs[message.jobId];
            if (state != null) state.isPaused = true;
          case EngineCommand.resumeJob:
            final state = jobs[message.jobId];
            if (state != null) state.isPaused = false;
        }
      }
    }
  }

  static Future<void> _runJob(
    SendPort sendPort,
    ReceivePort commandPort,
    EngineMessage message,
    Map<String, _JobState> jobs,
  ) async {
      final data = message.data;
    if (data == null) {
      sendPort.send(EngineCompletion(
        jobId: message.jobId,
        success: false,
        completedChapters: 0,
        failedChapters: 0,
      ));
      return;
    }

    final state = _JobState();
    jobs[message.jobId] = state;

    try {
      final seriesUrl = data['seriesUrl'] as String? ?? '';
      final seriesTitle = data['seriesTitle'] as String? ?? '';
      final adapterName = data['adapterName'] as String? ?? '';
      final chapterNumbers = (data['chapterNumbers'] as List?)?.cast<double>() ?? [];
      final chapterUrls = (data['chapterUrls'] as List?)?.cast<String>() ?? [];
      final chapterLabels = (data['chapterLabels'] as List?)?.cast<String>() ?? [];
      final outputFolder = data['outputFolder'] as String? ?? '';

      if (seriesUrl.isEmpty || outputFolder.isEmpty) {
        sendPort.send(EngineCompletion(
          jobId: message.jobId,
          success: false,
          completedChapters: 0,
          failedChapters: chapterNumbers.length,
        ));
        return;
      }

      final dataSource = RemoteDataSource(referer: seriesUrl);
      final adapter = resolveAdapter(seriesUrl, dataSource: dataSource);
      final pdfConverter = PdfConverter();

      final seriesDir = p.join(outputFolder, seriesTitle);
      final resultDir = p.join(seriesDir, 'Result');

      Directory(seriesDir).createSync(recursive: true);
      Directory(resultDir).createSync(recursive: true);

      await MetadataHelper.saveMetadataJson(
        seriesDir: seriesDir,
        title: seriesTitle,
        url: seriesUrl,
        adapterName: adapterName,
      );

      int completed = 0;
      int failed = 0;

      for (int i = 0; i < chapterNumbers.length; i++) {
        if (state.isCancelled) break;

        while (state.isPaused && !state.isCancelled) {
          await Future.delayed(const Duration(milliseconds: 500));
        }
        if (state.isCancelled) break;

        final chapterNum = chapterNumbers[i];
        final label = chapterLabels.length > i ? chapterLabels[i] : formatChapterLabel(chapterNum);
        final chapterUrl = chapterUrls.length > i ? chapterUrls[i] : seriesUrl;

        sendPort.send(EngineUpdate(
          jobId: message.jobId,
          chapterIndex: i,
          status: ChapterStatus.downloading,
        ));

        try {
          if (chapterUrl.isEmpty) {
            throw Exception('Chapter URL is empty');
          }

          final images = await adapter.getChapterImages(
            chapterUrl,
            isCancelled: () => state.isCancelled,
          );

          if (images.isEmpty) {
            sendPort.send(EngineUpdate(
              jobId: message.jobId,
              chapterIndex: i,
              status: ChapterStatus.failed,
              error: 'No images found',
            ));
            failed++;
            continue;
          }

          final tempDir = Directory.systemTemp.createTempSync('ch_${label}_');
          try {
            for (int j = 0; j < images.length; j++) {
              if (state.isCancelled) break;
              final ext = p.extension(Uri.tryParse(images[j])?.path ?? '.jpg');
              final filePath = p.join(tempDir.path, '${(j + 1).toString().padLeft(3, '0')}$ext');

              final dir = Directory(p.dirname(filePath));
              if (!dir.existsSync()) dir.createSync(recursive: true);

              await dataSource.downloadToFile(
                images[j],
                filePath,
                referer: chapterUrl,
              );

              sendPort.send(EngineUpdate(
                jobId: message.jobId,
                chapterIndex: i,
                status: ChapterStatus.downloading,
                progressPages: j + 1,
                totalPages: images.length,
              ));
            }

            if (state.isCancelled) {
              tempDir.deleteSync(recursive: true);
              sendPort.send(EngineUpdate(
                jobId: message.jobId,
                chapterIndex: i,
                status: ChapterStatus.failed,
              ));
              continue;
            }

            final pdfName = formatChapterPdfFilename(label);
            final pdfPath = p.join(resultDir, pdfName);

            final result = await pdfConverter.convertChapterToPdf(
              chapterDir: tempDir.path,
              outputPath: pdfPath,
            );

            if (result != null) {
              await MetadataHelper.saveChapterJson(
                seriesDir: seriesDir,
                chapterNumber: chapterNum,
                chapterLabel: label,
                pdfPath: pdfPath,
                pageCount: images.length,
              );

              sendPort.send(EngineUpdate(
                jobId: message.jobId,
                chapterIndex: i,
                status: ChapterStatus.completed,
                pdfPath: pdfPath,
                totalPages: images.length,
              ));
              completed++;
            } else {
              sendPort.send(EngineUpdate(
                jobId: message.jobId,
                chapterIndex: i,
                status: ChapterStatus.failed,
                error: 'PDF conversion failed',
              ));
              failed++;
            }
          } finally {
            if (tempDir.existsSync()) {
              tempDir.deleteSync(recursive: true);
            }
          }
        } catch (e) {
          sendPort.send(EngineUpdate(
            jobId: message.jobId,
            chapterIndex: i,
            status: ChapterStatus.failed,
            error: e.toString(),
          ));
          failed++;
        }
      }

      jobs.remove(message.jobId);

      sendPort.send(EngineCompletion(
        jobId: message.jobId,
        success: failed == 0,
        completedChapters: completed,
        failedChapters: failed,
      ));
    } catch (e) {
      jobs.remove(message.jobId);

      sendPort.send(EngineCompletion(
        jobId: message.jobId,
        success: false,
        completedChapters: 0,
        failedChapters: 0,
      ));
    }
  }
}

class _JobState {
  bool isCancelled = false;
  bool isPaused = false;
}
