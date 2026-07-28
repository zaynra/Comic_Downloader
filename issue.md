# Issue — Comic Downloader Mobile Build

## Tools
- **Flutter SDK**: `C:\Android\flutter` (Dart 3.7.2)
- **JDK**: `C:\Program Files\Android\Android Studio\jbr` (OpenJDK 21.0.5)
- **Android SDK**: `C:\Users\rafki\AppData\Local\Android\Sdk`
- **ADB**: `C:\Users\rafki\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- **Emulator**: Pixel_4 (android-36, x86_64), emulator-5554
- **NDK**: 26.3.11579264 + 27.0.12077973 (both installed)
- **Gradle**: 8.10.2 (wrapper)
- **AGP**: 8.7.0

## Issues

### 1. Gradle Build Tidak Selesai ✅ resolved
- `flutter run` stuck di "Running Gradle task 'assembleDebug'..."
- First build perlu download dependencies dari internet (~5-15 menit)
- **Solved**: Build berhasil dengan JDK 21 + AGP 8.7.0 + Kotlin 1.9.22
- Root cause: JDK 24 corrupted Gradle daemon — JDK 24 sudah dihapus manual via Settings > Apps
- Catatan: `coreLibraryDesugaringEnabled = true` + `desugar_jdk_libs:2.1.4` + `jvmTarget = "11"` diperlukan untuk `flutter_local_notifications`

### 2. Flutter `.bat` Wrapper Hang
- `flutter.bat`, `dart.bat` tidak bisa jalan
- Workaround: langsung pakai snapshot
  ```
  & "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" run -d emulator-5554
  ```

### 3. Missing INTERNET Permission ✅ resolved
- `android/app/src/main/AndroidManifest.xml` sudah ditambahi: INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED

### 4. Dual Project Structure ✅ resolved
- Root sebagai source of truth, `build_temp/` sebagai build target
- Sync script `sync_to_build.ps1` untuk copy lib/ + pubspec.yaml dari root ke build_temp
- Gunakan: `.\sync_to_build.ps1 -PubGet -Analyze -Run`

### 5. Gradle Redirect Build Dir ✅ mitigated
- `android/build.gradle.kts` redirect build output ke `../../build`
- Menyebabkan non-fatal warning `"this and base files have different roots"` dari Kotlin incremental compiler
- Build tetap berhasil meskipun ada warning ini

## Todo Selesai ✅ (Semua item dari `todo.md` sudah dikerjakan)
- [x] Fallback JS-render webview_flutter (Phase 1)
- [x] Isolate/background terpisah via `Isolate.spawn` (Phase 3)
- [x] Foreground service via `flutter_background_service` (Phase 3)
- [x] Local notifications via `flutter_local_notifications` (Phase 5)
- [x] Bersihkan file sementara — port `cleaner.dart` (Phase 6)
- [x] Mini Preview + deep link Comic Viewer (Phase 7)
- [x] Polish & rilis internal (INTERNET permission, error handling, build APK, dual project structure)

## Remaining
- [ ] Test manual di emulator/device
- [ ] Build APK release dengan signing config
