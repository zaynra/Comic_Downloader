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

## Critical Bug — Download Hangs at "file 0 per N"
**Symptom**: Pressing download navigates to queue screen, shows progress "file 0 per 2" (or similar), then hangs indefinitely. No actual download occurs.

**Root cause (suspect)**:
- `downloadToFile()` in `RemoteDataSource` silently returns `false` on failure — engine ignores the return value
- No `Referer` header on image requests — many CDNs block without it on Android 14+
- `Dio` instance in isolate may have timeout issues (`receiveTimeout: 30s` not applied to `download()`)
- `sendTimeout` not configured — request can hang forever on slow networks

**Fix applied** (not yet verified):
- [x] Changed `downloadToFile()` to throw on failure instead of returning `false` silently
- [x] Added `Referer` header (chapter URL) to image download requests
- [x] Added `sendTimeout: 15s` to Dio config
- [x] Engine now creates `RemoteDataSource` with `referer: seriesUrl` and passes it to `resolveAdapter()`
- [x] Created `download_foreground` notification channel in `NotificationService.init()` to fix `CannotPostForegroundServiceNotificationException` on Android 15

**Needs further investigation**:
- [ ] Verify fix works on emulator (download not tested after latest changes)
- [ ] Check if `adapter.getChapterImages()` returns correct image URLs for the target site
- [ ] Add per-page download timeout or retry logic in engine
- [ ] Consider using `compute()` instead of `Isolate.spawn` for simpler debugging

## Critical Bug — Download button crashed app (FIXED)
**Symptom**: Pressing "Download N Chapter" caused app to force-close.
**Root cause**: `MissingForegroundServiceTypeException` on Android 14+ (targetSDK=35).
**Fix**: Added `android:foregroundServiceType="dataSync"` to BackgroundService in AndroidManifest.xml.

## Resolved Issues
### 1. Gradle Build Tidak Selesai ✅
### 2. Flutter `.bat` Wrapper Hang ✅
### 3. Missing INTERNET Permission ✅
### 4. Dual Project Structure ✅
### 5. Gradle Redirect Build Dir ✅

---

# ✅ Quality of Life — All 7 Screens Completed

## 1. HomePage ✅
- Empty state with illustration + guide text + "Cari Komik" button
- URL input with real-time validation (invalid URL / unsupported site)
- Recent URLs chips (last 5, persisted, with "Clear All" button)
- Active queue cards with real-time progress bar + active chapter name
- Shows which chapter is currently downloading
- SnackBar on error

## 2. SearchPage ✅
- Debounced search (500ms) with cancel-safe logic
- Search history v2 (persisted with timestamps, shows "5m lalu")
- Delete individual history items + "Hapus Semua" button
- Pull-to-refresh on search results
- Better error categorization (network vs 404 vs generic)
- Auto-focus search field on page load
- Example text in empty state
- Result count at bottom of results list

## 3. SeriesDetailPage ✅
- Download crash fixed (try-catch, chapter URLs passed from UI)
- Chapter range selection (long-press to select a range)
- Quick-select chips: Semua, None, Balik, Baru, Lanjutkan, 5, 10, Range
- Invert selection (Balik)
- Batch range input with live preview count
- Sort toggle (ascending/descending) in AppBar
- Chapter filter/search field with filtered count badge
- Info bar: total chapters, existing badge, selected count
- "Start" badge on range start chapter
- Existing chapters dimmed with checkmark
- Quick buttons always visible by default (no need to expand)

## 4. DownloadQueuePage ✅
- TabBar: "Berjalan (N)" / "Selesai (N)"
- Expandable job cards — tap to see ALL chapters (no 10 limit)
- Per-chapter status using Material icons (not emojis): ✅⬇️❌⏳
- Chapter progress (X/Y pages)
- Relative timestamps: "baru saja", "5m lalu", "2j lalu"
- PopupMenu with: Retry All Failed, Clear Completed, Clear All
- Swipe-to-delete on job cards with confirmation dialog
- Failed chapter visualization
- Empty state illustrations per tab

## 5. SettingsPage ✅
- **Visual folder picker** via `file_picker` (`getDirectoryPath()`) — no more manual path typing
- "Open Folder" button to open output folder in file explorer
- Slider-based edit dialog for parallel/retry (instead of text input)
- Confirmation dialog before running cleaner
- Cleaner result feedback (number of files deleted)
- Folder path display with full path shown below
- Quick action: tap folder tile OR tap edit icon to pick folder

## 6. AdapterManagerPage ✅
- Custom adapters persisted via `jsonEncode/jsonDecode` (robust, not fragile string parsing)
- Edit custom adapter (tap edit icon → pre-filled dialog)
- Delete with confirmation dialog
- Drag-to-reorder via `ReorderableListView`
- Swipe-to-delete with dismissible
- Edit/delete icon buttons per adapter

## 7. MiniPreviewPage ✅
- Fixed `_loadMore` bug: now appends to existing list (was replacing)
- Paginated loading: 10 images at a time, "Muat 10 Lagi (N tersisa)" button
- Full-screen pinch-to-zoom viewer with `InteractiveViewer`
- Page counter: "Halaman X dari Y"
- Chapter navigation arrows in full-screen mode (prev/next)
- Loading indicator per image via `frameBuilder`
- Page indicator footer: "Halaman X dari Y"

## Global Improvements
- [ ] Shimmer loading placeholders (future)
- [ ] Offline indicator banner (future)
- [ ] URL launcher for Comic Viewer deep link (needs `url_launcher` dep)
- [ ] Haptic feedback on key actions (future)
- [ ] Multi-language support (future)
