import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/repositories/download_repository.dart';
import '../../domain/models/download_job.dart';

final downloadRepositoryProvider = Provider<DownloadRepository>((_) {
  return DownloadRepository();
});

final downloadJobsProvider = StreamProvider<List<DownloadJob>>((ref) {
  final repo = ref.watch(downloadRepositoryProvider);
  return Stream.periodic(const Duration(milliseconds: 500), (_) => repo.jobs);
});

final activeDownloadJobsProvider = Provider<List<DownloadJob>>((ref) {
  final jobs = ref.watch(downloadJobsProvider).valueOrNull ?? [];
  return jobs.where((j) => !j.isDone).toList();
});

final completedDownloadJobsProvider = Provider<List<DownloadJob>>((ref) {
  final jobs = ref.watch(downloadJobsProvider).valueOrNull ?? [];
  return jobs.where((j) => j.isDone).toList();
});
