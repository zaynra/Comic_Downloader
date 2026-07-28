# todo.md — Comic Downloader Mobile: Roadmap

Format fase mengikuti `PROGRESS.md` milik `Comic_Viewer`. Target: sideload APK, single-user, output kompatibel dengan `Comic_Viewer`.

## Phase 0 — Skeleton ✅
- [x] Project structure Clean Architecture (data/domain/presentation)
- [x] Setup Riverpod, GoRouter, Vivid Ink dark theme
- [x] Folder picker (manual path input dialog)
- [x] Folder output setting (shared_preferences)

## Phase 1 — Site Adapter Layer (ported from `streaming_pdf_downloader.py`)
- [x] Interface `BaseSiteAdapter`: `search()`, `getChapters()`, `getChapterImages()`
- [x] `GenericSiteAdapter` — pakai `dio` + `html` parser, tanpa Selenium
- [x] `DemonicScansAdapter` — selector `img.imgholder`, domain rewrite
- [x] `resolveAdapter()` by domain
- [x] Fallback JS-render: `webview_flutter`

## Phase 2 — Search & Series Detail UI ✅
- [x] `SearchPage` dengan hasil pencarian per adapter
- [x] `SeriesDetailPage` multi-select chapter + download button
- [x] Resume detection via folder output existing chapters

## Phase 3 — Download Engine (ported streaming logic)
- [x] Downloader gambar per halaman dengan retry
- [x] Cancellation token per job (pengganti `threading.Event`)
- [x] Parallel download configurable dari Settings
- [x] Isolate/background terpisah (DownloadEngine via `Isolate.spawn`)
- [x] Foreground service (`flutter_background_service`)

## Phase 4 — PDF Conversion ✅ (ported `folder_to_pdf.py` + `streaming_pdf_downloader.py`)
- [x] Gambar → PDF on-device (manual PDF builder, tanpa external dep)
- [x] Natural sort halaman sebelum digabung
- [x] Output: `Chapter_XXXX.pdf` (4-digit padding)
- [x] Generate `metadata.json` & `Chapter_XXXX.json`

## Phase 5 — Queue & Notifikasi (ported)
- [x] `DownloadQueuePage`: progress real-time, pause/resume/cancel
- [x] Local notification (`flutter_local_notifications`)
- [x] Retry otomatis (built into download engine)

## Phase 6 — Settings & Adapter Manager (ported)
- [x] Section Tampilan/Unduhan/Penyimpanan/Adapter/Tentang
- [x] `AdapterManagerPage`: toggle adapter
- [x] "Bersihkan File Sementara" (port `cleaner.py`)

## Phase 7 — Mini Preview (opsional)
- [x] `MiniPreviewPage` (preview gambar via filesystem)
- [x] Deep link "Buka di Comic Viewer" (via `comic-viewer://` scheme)

## Phase 8 — Polish & Rilis Internal
- [x] Missing INTERNET + FOREGROUND_SERVICE + POST_NOTIFICATIONS permission di `AndroidManifest.xml` main
- [x] Error handling eksplisit (user-facing error messages di semua page)
- [ ] Test manual (perlu dijalankan di emulator/device)
- [x] Build APK debug berhasil (100.8 MB)
- [x] Gradle build first time lambat — sudah berhasil build dengan JDK 21 + AGP 8.7.0 + Kotlin 1.9.22
- [x] Dual project structure — sync script `sync_to_build.ps1`

## Catatan
- Tidak perlu App Store/Play Store compliance.
- Tidak perlu akun/login — semua konfigurasi (adapter, folder, Telegram token jika dipertahankan) disimpan lokal via `shared_preferences`.
- Prioritas: hasil download harus 100% kompatibel dibaca `Comic_Viewer` sebelum optimasi lain dikerjakan.
