import 'dart:async';
import 'package:flutter_background_service/flutter_background_service.dart';

class ForegroundServiceManager {
  static final ForegroundServiceManager _instance = ForegroundServiceManager._();
  static ForegroundServiceManager get instance => _instance;
  ForegroundServiceManager._();

  bool _isRunning = false;

  Future<void> init() async {
    final service = FlutterBackgroundService();

    await service.configure(
      androidConfiguration: AndroidConfiguration(
        onStart: foregroundServiceOnStart,
        autoStart: false,
        isForegroundMode: true,
        autoStartOnBoot: false,
        notificationChannelId: 'download_foreground',
        initialNotificationTitle: 'Comic Downloader',
        initialNotificationContent: 'Mengunduh komik...',
        foregroundServiceNotificationId: 888,
      ),
      iosConfiguration: IosConfiguration(
        autoStart: false,
        onForeground: foregroundServiceOnStart,
        onBackground: _onIosBackground,
      ),
    );
  }

  Future<bool> start() async {
    if (_isRunning) return true;
    final service = FlutterBackgroundService();
    await service.startService();
    _isRunning = true;
    return true;
  }

  Future<bool> stop() async {
    if (!_isRunning) return true;
    final service = FlutterBackgroundService();
    service.invoke('stopService');
    _isRunning = false;
    return true;
  }

  void updateNotification({String? title, String? content, int? progress, int? maxProgress}) {
    final service = FlutterBackgroundService();
    service.invoke('updateNotification', {
      if (title != null) 'title': title,
      if (content != null) 'content': content,
      if (progress != null) 'progress': progress,
      if (maxProgress != null) 'maxProgress': maxProgress,
    });
  }

  bool get isRunning => _isRunning;

  @pragma('vm:entry-point')
  static bool _onIosBackground(ServiceInstance service) {
    return true;
  }
}

@pragma('vm:entry-point')
void foregroundServiceOnStart(ServiceInstance service) {
  if (service is AndroidServiceInstance) {
    service.on('updateNotification').listen((data) {
      if (data is Map<String, dynamic>) {
        service.setForegroundNotificationInfo(
          title: (data['title'] as String?) ?? 'Comic Downloader',
          content: (data['content'] as String?) ?? 'Mengunduh...',
        );
      }
    });

    service.on('stopService').listen((_) {
      service.stopSelf();
    });
  }
}
