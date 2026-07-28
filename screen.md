# screen.md — Comic Downloader Mobile (Screen & Navigation Spec)

Tema: dark theme, aksen lavender `#CFBCFF`, Material 3, GoRouter, Bahasa Indonesia.

## Peta Navigasi (GoRouter) — 7 screens
```
/                     → HomePage         (URL input, recent chips, queue cards, FAB search)
/search               → SearchPage       (debounced search, history, pull-to-refresh)
/series/:id           → SeriesDetailPage  (range select, quick-chips, sort, filter, batch input)
/queue                → DownloadQueuePage (tab: active/done, expandable cards, per-chapter status)
/settings             → SettingsPage     (tampilan, unduhan, penyimpanan, adapter, tentang)
/settings/adapters    → AdapterManagerPage (toggle adapter, tambah generic)
/preview/:chapterId   → MiniPreviewPage  (preview 5 gambar, deep link Comic Viewer)
```

## 1. HomePage
- **URL Input Card**: TextField + paste button + "Buka Series/Chapter" button
  - Real-time URL validation (invalid URL → error text)
  - Paste auto-submits if valid
- **Recent URLs chips**: Last 5 visited sites (persisted, 10 history limit)
- **Active Queue section**: Real-time progress bars, chapter count, pause/status indicator
  - Tap card → `/queue`
- **Empty state**: Illustration + guide text + "Cari Komik" FilledButton
- **FAB**: Icon search → `/search`

## 2. SearchPage
- **Debounced search**: Auto-search 500ms after typing stops
- **Search bar**: TextField + paste button + clear button
- **Cari / Buka URL button**: Detect if input is URL or search query
- **Search history**: Persisted in SharedPreferences, shown as list on empty state
  - Tap history → auto-search
  - Delete individual items
- **Results**: Card per Series (thumbnail, title, adapter, chapter count)
  - Tap → `/series/:id`
- **Pull-to-refresh**: RefreshIndicator on search results
- **Error states**: Distinguish network error, not-found, generic

## 3. SeriesDetailPage
- **Info bar**: Chapter count, existing badge, selected count
- **Sort toggle**: AppBar icon — ascending/descending
- **Quick-select chips row**: 
  - Semua / None / Baru / Lanjutkan / 5 / 10 / Range
  - Collapsible (expand/collapse toggle)
- **Filter field**: Search/filter chapters by number or label
- **Chapter list**: Cards with selection indicator
  - Tap → toggle single selection
  - Long-press → select range (from last tap to current)
  - "Start" badge on range start
  - Existing chapters shown grayed out with checkmark
- **Range input dialog**: Type "1-10,15,20-25" → batch select
- **Bottom bar**: "Download N Chapter" button (visible when selection not empty)

## 4. DownloadQueuePage
- **TabBar**: "Berjalan (N)" / "Selesai (N)"
- **Job cards**: Series title, progress bar, status chip, chapter count
  - Tap → expand/collapse
  - Expanded: per-chapter status rows (✅⬇️❌⏳ + page progress)
- **Action buttons**:
  - Active: Pause/Resume, Stop
  - Done: Preview, Retry, Delete
- **Relative timestamps**: "Selesai 5m lalu"

## 5. SettingsPage
- **Tampilan**: Tema (dark fixed)
- **Unduhan**: Parallel max, retry count (edit dialog)
- **Penyimpanan**: Output folder (manual path), "Bersihkan File Sementara"
- **Adapter**: Kelola situs → `/settings/adapters`
- **Tentang**: Versi 1.0.0

## 6. AdapterManagerPage
- Toggle Generic / DemonicScans (persisted via shared_preferences)
- Tambah adapter generic (base URL + CSS selector dialog)

## 7. MiniPreviewPage
- 5 gambar pertama dari folder chapter
- Tombol "Buka di Comic Viewer" (deep link)

## Services (non-screen)
- `NotificationService` — flutter_local_notifications
- `ForegroundServiceManager` — flutter_background_service
- `DownloadEngine` — Isolate.spawn (now with try-catch, proper chapter URLs)
- `ImageCleaner` — port cleaner.py
