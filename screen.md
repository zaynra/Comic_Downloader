# screen.md — Comic Downloader Mobile (Screen & Navigation Spec)

Tema: dark theme, aksen lavender `#CFBCFF`, Google Fonts Inter, Material Symbols icons, GoRouter, teks UI Bahasa Indonesia.

## Peta Navigasi (GoRouter) — 7 screens
```
/                     → HomePage         (URL input card + antrian aktif)
/search               → SearchPage       (cari judul/URL)
/series/:id           → SeriesDetailPage (daftar chapter + download)
/queue                → DownloadQueuePage(progress real-time)
/settings             → SettingsPage     (konfigurasi app)
/settings/adapters    → AdapterManagerPage (toggle adapter)
/preview/:chapterId   → MiniPreviewPage  (preview gambar chapter)
```

## 1. HomePage
- Card input: TextField URL + paste button + "Buka Series/Chapter" button
- Dropdown adapter (Generic / DemonicScans)
- Section "Antrian Aktif": daftar job berjalan, tap → `/queue`
- FAB: icon search → `/search`

## 2. SearchPage
- Search bar + paste button + "Cari / Buka URL" button
- List hasil: thumbnail, judul, adapter, chapter count
- Error state + empty state

## 3. SeriesDetailPage
- List chapter checkbox multi-select
- Badge "sudah ada di folder" (resume detection via filesystem)
- Tombol "Lanjutkan" (download dari chapter terakhir tersimpan)
- Bottom bar: "Download N Chapter" — cek folder output, create job, start engine

## 4. DownloadQueuePage
- Card per job: progress bar, status chip, detail chapter aktif
- Tombol: pause/resume, cancel, retry, preview, delete
- Empty state: "Belum ada unduhan"

## 5. SettingsPage
- **Tampilan**: tema
- **Unduhan**: paralel max, retry count
- **Penyimpanan**: folder output (manual path), "Bersihkan File Sementara" (port cleaner.py → cleaner.dart)
- **Adapter**: kelola situs → `/settings/adapters`
- **Tentang**: versi

## 6. AdapterManagerPage
- Toggle Generic / DemonicScans (persisted via shared_preferences)
- Tambah adapter generic (base URL + CSS selector dialog)

## 7. MiniPreviewPage
- 5 gambar pertama dari folder chapter (preview cepat)
- Tombol "Buka di Comic Viewer" (deep link `comic-viewer://open?path=...`)

## Services (non-screen)
- `NotificationService` — flutter_local_notifications (progress, complete, error)
- `ForegroundServiceManager` — flutter_background_service (keep alive saat background)
- `DownloadEngine` — Isolate.spawn untuk background download
- `ImageCleaner` — port cleaner.py, hapus banner/iklan dari gambar chapter
