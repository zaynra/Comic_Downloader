import 'package:go_router/go_router.dart';
import '../pages/home_page.dart';
import '../pages/search_page.dart';
import '../pages/series_detail_page.dart';
import '../pages/download_queue_page.dart';
import '../pages/settings_page.dart';
import '../pages/adapter_manager_page.dart';
import '../pages/mini_preview_page.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(
      path: '/',
      name: 'home',
      builder: (_, __) => const HomePage(),
    ),
    GoRoute(
      path: '/search',
      name: 'search',
      builder: (_, __) => const SearchPage(),
    ),
    GoRoute(
      path: '/series/:id',
      name: 'seriesDetail',
      builder: (_, state) => SeriesDetailPage(
        seriesId: state.pathParameters['id']!,
      ),
    ),
    GoRoute(
      path: '/queue',
      name: 'queue',
      builder: (_, __) => const DownloadQueuePage(),
    ),
    GoRoute(
      path: '/settings',
      name: 'settings',
      builder: (_, __) => const SettingsPage(),
    ),
    GoRoute(
      path: '/settings/adapters',
      name: 'adapterManager',
      builder: (_, __) => const AdapterManagerPage(),
    ),
    GoRoute(
      path: '/preview/:chapterId',
      name: 'preview',
      builder: (_, state) => MiniPreviewPage(
        pdfPath: state.pathParameters['chapterId'] ?? '',
        seriesTitle: state.uri.queryParameters['title'] ?? 'Preview',
      ),
    ),
  ],
);
