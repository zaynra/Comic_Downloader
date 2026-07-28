# todo.md — Comic Downloader Mobile: Roadmap

Status: **All 7 screens upgraded with Quality of Life improvements. Download still hangs — need further debugging.**

## ✅ Phase 0-8 (MVP) — Completed
- [x] Fase 0: Skeleton — Clean Architecture, Riverpod, GoRouter, Vivid Ink dark theme
- [x] Fase 1: Site Adapter Layer — GenericSiteAdapter, DemonicScansAdapter, resolveAdapter
- [x] Fase 2: Search & Series Detail UI
- [x] Fase 3: Download Engine — Isolate.spawn, foreground service, cancel/pause/resume
- [x] Fase 4: PDF Conversion — image→PDF, natural sort, metadata JSON
- [x] Fase 5: Queue & Notifikasi — progress, flutter_local_notifications, auto retry
- [x] Fase 6: Settings & Adapter Manager
- [x] Fase 7: Mini Preview
- [x] Fase 8: Polish & Rilis Internal — permissions, error handling, dual project structure

## ✅ Critical Bug Fix — Download Crash
- [x] Isolate try-catch, chapter URLs passed from UI, null-safe types
- [x] Stub `_resolveChapterUrl` removed — real chapter URLs used in engine
- [x] `MissingForegroundServiceTypeException` fixed — added `foregroundServiceType` to AndroidManifest
- [x] `CannotPostForegroundServiceNotificationException` fixed — created `download_foreground` notification channel

## ❌ Critical Bug — Download Hangs
- [x] Changed `downloadToFile()` to throw on failure instead of silent false
- [x] Added `Referer` header + `sendTimeout` to image download requests
- [x] Engine creates `RemoteDataSource` with referer, passes to adapter
- [ ] **Still hangs** — needs further investigation on emulator

## ✅ Quality of Life — All 7 Screens

### HomePage
- [x] Better empty state with guide text + "Cari Komik" button
- [x] Real-time URL validation (invalid, unsupported site)
- [x] Recent URLs chips (persisted, last 5, with Clear All)
- [x] Active queue cards with progress bar + active chapter label
- [x] Error SnackBars

### SearchPage
- [x] Debounced search (500ms, cancel-safe)
- [x] Search history with timestamps ("5m lalu"), delete individual + clear all
- [x] Pull-to-refresh on results
- [x] Better error messages (network vs 404 vs generic)
- [x] Auto-focus on page load
- [x] Result count at bottom

### SeriesDetailPage
- [x] Download crash fixed
- [x] Range selection (long-press)
- [x] Quick-select chips: Semua, None, Balik, Baru, Lanjutkan, 5, 10, Range
- [x] Invert selection
- [x] Batch range input dialog with live preview count
- [x] Sort toggle (ascending/descending)
- [x] Chapter filter with filtered count badge
- [x] Info bar with counts

### DownloadQueuePage
- [x] TabBar: Berjalan / Selesai
- [x] Expandable cards (all chapters shown)
- [x] Material icons for chapter status (not emojis)
- [x] Per-chapter page progress
- [x] Relative timestamps
- [x] PopupMenu: Retry All Failed, Clear Completed, Clear All
- [x] Swipe-to-delete with confirmation
- [x] Empty state illustrations per tab

### SettingsPage
- [x] Visual folder picker via file_picker (no manual path typing)
- [x] "Open Folder" button for output folder
- [x] Slider-based edit for parallel/retry values
- [x] Confirmation dialog before cleaner
- [x] Full folder path display

### AdapterManagerPage
- [x] Robust JSON persistence for custom adapters
- [x] Edit custom adapters
- [x] Delete with confirmation
- [x] Drag-to-reorder (ReorderableListView)
- [x] Swipe-to-delete

### MiniPreviewPage
- [x] Paginated loading (10 at a time)
- [x] Fixed _loadMore bug (append, not replace)
- [x] Full-screen pinch-to-zoom viewer
- [x] Page counter + nav arrows in full-screen
- [x] Loading indicator per image (frameBuilder)

## 📊 Stats
- `flutter analyze`: **0 errors, 0 warnings**, ~42 info-only lint hints
- APK build: successful
- Codebase: 7 screens, clean Dart/Flutter, Material 3 dark theme

## 🔮 Future Ideas
- Shimmer loading skeletons
- Offline indicator banner
- Comic Viewer deep link via url_launcher
- Haptic feedback on key actions
- Multi-language support (EN/ID)
- Persist download queue across app restarts
