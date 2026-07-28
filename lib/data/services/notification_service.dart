import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  static final NotificationService _instance = NotificationService._();
  static NotificationService get instance => _instance;
  NotificationService._();

  final FlutterLocalNotificationsPlugin _plugin = FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  Future<void> init() async {
    if (_initialized) return;
    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    const settings = InitializationSettings(
      android: androidSettings,
      iOS: iosSettings,
    );
    await _plugin.initialize(
      settings,
      onDidReceiveNotificationResponse: _onNotificationTap,
    );
    _initialized = true;
  }

  void _onNotificationTap(NotificationResponse response) {}

  Future<void> showProgress({
    required int id,
    required String title,
    required String body,
    required int progress,
    required int maxProgress,
  }) async {
    final androidDetails = AndroidNotificationDetails(
      'download_channel',
      'Unduhan',
      channelDescription: 'Progress unduhan komik',
      importance: Importance.low,
      priority: Priority.low,
      onlyAlertOnce: true,
      showProgress: true,
      maxProgress: maxProgress,
      progress: progress,
      ongoing: true,
      autoCancel: false,
    );
    await _plugin.show(id, title, body, NotificationDetails(android: androidDetails));
  }

  Future<void> showCompletion({
    required int id,
    required String title,
    required String body,
  }) async {
    final androidDetails = AndroidNotificationDetails(
      'download_channel',
      'Unduhan',
      channelDescription: 'Progress unduhan komik',
      importance: Importance.defaultImportance,
      priority: Priority.defaultPriority,
      showProgress: false,
    );
    await _plugin.show(id, title, body, NotificationDetails(android: androidDetails));
  }

  Future<void> showError({
    required int id,
    required String title,
    required String body,
  }) async {
    final androidDetails = AndroidNotificationDetails(
      'download_error_channel',
      'Error Unduhan',
      channelDescription: 'Notifikasi error unduhan komik',
      importance: Importance.high,
      priority: Priority.high,
      showProgress: false,
    );
    await _plugin.show(id, title, body, NotificationDetails(android: androidDetails));
  }

  Future<void> cancel(int id) async {
    await _plugin.cancel(id);
  }

  Future<void> cancelAll() async {
    await _plugin.cancelAll();
  }
}
