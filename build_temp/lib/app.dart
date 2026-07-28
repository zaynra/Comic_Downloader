import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/theme/app_theme.dart';
import 'data/services/notification_service.dart';
import 'data/services/foreground_service.dart';
import 'presentation/router/app_router.dart';
import 'presentation/providers/settings_provider.dart';

class ComicDownloaderApp extends ConsumerStatefulWidget {
  const ComicDownloaderApp({super.key});

  @override
  ConsumerState<ComicDownloaderApp> createState() => _ComicDownloaderAppState();
}

class _ComicDownloaderAppState extends ConsumerState<ComicDownloaderApp> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      await NotificationService.instance.init();
      await ForegroundServiceManager.instance.init();
      await ref.read(settingsProvider.notifier).load();
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'Comic Downloader',
      theme: AppTheme.dark,
      routerConfig: appRouter,
      debugShowCheckedModeBanner: false,
    );
  }
}
