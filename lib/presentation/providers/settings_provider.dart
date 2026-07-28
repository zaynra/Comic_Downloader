import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppSettings {
  final int maxParallelDownloads;
  final int retryCount;
  final int timeoutSeconds;
  final String outputFolder;
  final bool themeDark;

  const AppSettings({
    this.maxParallelDownloads = 3,
    this.retryCount = 3,
    this.timeoutSeconds = 30,
    this.outputFolder = '',
    this.themeDark = true,
  });

  AppSettings copyWith({
    int? maxParallelDownloads,
    int? retryCount,
    int? timeoutSeconds,
    String? outputFolder,
    bool? themeDark,
  }) {
    return AppSettings(
      maxParallelDownloads: maxParallelDownloads ?? this.maxParallelDownloads,
      retryCount: retryCount ?? this.retryCount,
      timeoutSeconds: timeoutSeconds ?? this.timeoutSeconds,
      outputFolder: outputFolder ?? this.outputFolder,
      themeDark: themeDark ?? this.themeDark,
    );
  }
}

class SettingsNotifier extends StateNotifier<AppSettings> {
  SettingsNotifier() : super(const AppSettings());

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    state = AppSettings(
      maxParallelDownloads: prefs.getInt('max_parallel') ?? 3,
      retryCount: prefs.getInt('retry_count') ?? 3,
      timeoutSeconds: prefs.getInt('timeout') ?? 30,
      outputFolder: prefs.getString('output_folder') ?? '',
      themeDark: prefs.getBool('theme_dark') ?? true,
    );
  }

  Future<void> setMaxParallelDownloads(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('max_parallel', value);
    state = state.copyWith(maxParallelDownloads: value);
  }

  Future<void> setRetryCount(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('retry_count', value);
    state = state.copyWith(retryCount: value);
  }

  Future<void> setTimeoutSeconds(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('timeout', value);
    state = state.copyWith(timeoutSeconds: value);
  }

  Future<void> setOutputFolder(String value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('output_folder', value);
    state = state.copyWith(outputFolder: value);
  }

  Future<void> setThemeDark(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('theme_dark', value);
    state = state.copyWith(themeDark: value);
  }
}

final settingsProvider = StateNotifierProvider<SettingsNotifier, AppSettings>((ref) {
  return SettingsNotifier();
});
