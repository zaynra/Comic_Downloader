import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../data/datasources/adapter_resolver.dart';
import '../../domain/models/series.dart';

class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final _searchController = TextEditingController();
  final _focusNode = FocusNode();
  List<Series> _results = [];
  List<Map<String, dynamic>> _searchHistory = [];
  bool _isSearching = false;
  String? _error;
  Timer? _debounce;
  bool _pendingDebounce = false;

  @override
  void initState() {
    super.initState();
    _loadSearchHistory();
    _focusNode.requestFocus();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _focusNode.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _loadSearchHistory() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList('search_history_v2') ?? [];
    final history = raw.map((e) {
      final parts = e.split('|||');
      return {'query': parts[0], 'time': parts.length > 1 ? parts[1] : ''};
    }).toList();
    if (mounted) setState(() => _searchHistory = history);
  }

  Future<void> _saveSearchQuery(String query) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList('search_history_v2') ?? [];
    final now = DateTime.now().millisecondsSinceEpoch.toString();
    final entry = '$query|||$now';
    raw.removeWhere((e) => e.startsWith('$query|||'));
    raw.insert(0, entry);
    if (raw.length > 20) raw.removeRange(20, raw.length);
    await prefs.setStringList('search_history_v2', raw);
    if (mounted) {
      setState(() => _searchHistory = raw.map((e) {
        final parts = e.split('|||');
        return {'query': parts[0], 'time': parts.length > 1 ? parts[1] : ''};
      }).toList());
    }
  }

  void _onSearchChanged(String query) {
    _pendingDebounce = true;
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 500), () {
      if (!_pendingDebounce) return;
      if (query.trim().isNotEmpty && Uri.tryParse(query)?.hasScheme != true) {
        _search(query.trim());
      }
      _pendingDebounce = false;
    });
  }

  Future<void> _search(String query) async {
    _pendingDebounce = false;
    _debounce?.cancel();
    if (query.trim().isEmpty) return;
    setState(() { _isSearching = true; _error = null; });

    try {
      await _saveSearchQuery(query.trim());
      final adapter = resolveAdapter(query);
      final results = await adapter.search(query);
      if (!mounted) return;
      setState(() {
        _results = results;
        if (results.isEmpty) _error = 'Tidak ada hasil untuk "$query"';
      });
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString();
      setState(() {
        _results = [];
        if (msg.contains('Connection') || msg.contains('Timeout') || msg.contains('Socket')) {
          _error = 'Gagal terhubung ke server. Periksa koneksi internet.';
        } else if (msg.contains('404') || msg.contains('not found')) {
          _error = 'Halaman tidak ditemukan. URL mungkin salah.';
        } else {
          _error = 'Gagal mencari: ${msg.length > 100 ? msg.substring(0, 100) : msg}';
        }
      });
    } finally {
      if (mounted) setState(() => _isSearching = false);
    }
  }

  Future<void> _openUrl(String url) async {
    if (url.trim().isEmpty) return;
    try {
      resolveAdapter(url);
      await _saveSearchQuery(url);
      if (mounted) context.push('/series/${Uri.encodeComponent(url.trim())}');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('URL tidak didukung oleh adapter manapun')),
        );
      }
    }
  }

  Future<void> _pasteFromClipboard() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (data?.text != null && data!.text!.isNotEmpty) {
      _searchController.text = data.text!;
      _focusNode.unfocus();
      final text = data.text!;
      if (Uri.tryParse(text)?.hasScheme == true) {
        _openUrl(text);
      } else {
        _search(text);
      }
    }
  }

  void _onSubmit(String value) {
    _pendingDebounce = false;
    _debounce?.cancel();
    if (Uri.tryParse(value)?.hasScheme == true) {
      _openUrl(value);
    } else {
      _search(value);
    }
  }

  String _formatHistoryTime(String ts) {
    if (ts.isEmpty) return '';
    final dt = DateTime.tryParse(ts);
    if (dt == null) return '';
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return 'baru saja';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m lalu';
    if (diff.inHours < 24) return '${diff.inHours}j lalu';
    if (diff.inDays < 7) return '${diff.inDays}h lalu';
    return dt.toString().substring(0, 10);
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Cari Komik'),
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(AppDimensions.spacingMd),
        child: Column(
          children: [
            TextField(
              controller: _searchController,
              focusNode: _focusNode,
              decoration: InputDecoration(
                hintText: 'Judul komik atau URL',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (_searchController.text.isNotEmpty)
                      IconButton(
                        icon: const Icon(Icons.clear, size: 20),
                        tooltip: 'Hapus',
                        onPressed: () {
                          _searchController.clear();
                          _pendingDebounce = false;
                          _debounce?.cancel();
                          setState(() { _results = []; _error = null; });
                          _focusNode.requestFocus();
                        },
                      ),
                    IconButton(
                      icon: const Icon(Icons.paste_outlined),
                      tooltip: 'Tempel dari clipboard',
                      onPressed: _pasteFromClipboard,
                    ),
                  ],
                ),
                border: const OutlineInputBorder(),
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
              ),
              textInputAction: TextInputAction.search,
              onChanged: _onSearchChanged,
              onSubmitted: _onSubmit,
            ),
            const SizedBox(height: AppDimensions.spacingSm),
            SizedBox(
              width: double.infinity,
              height: 44,
              child: OutlinedButton.icon(
                onPressed: () {
                  if (_searchController.text.trim().isNotEmpty) {
                    _onSubmit(_searchController.text.trim());
                  }
                },
                icon: const Icon(Icons.arrow_forward, size: 18),
                label: const Text('Cari / Buka URL'),
              ),
            ),
            const SizedBox(height: AppDimensions.spacingMd),
            if (_isSearching)
              const Expanded(
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null)
              Expanded(
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.all(AppDimensions.spacingMd),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.error_outline, size: 48, color: AppColors.error.withValues(alpha: 0.7)),
                        const SizedBox(height: AppDimensions.spacingMd),
                        Text(_error!, style: textTheme.bodyMedium?.copyWith(color: AppColors.onSurfaceVariant),
                            textAlign: TextAlign.center),
                        const SizedBox(height: AppDimensions.spacingLg),
                        FilledButton.icon(
                          onPressed: () => _search(_searchController.text.trim()),
                          icon: const Icon(Icons.refresh),
                          label: const Text('Coba Lagi'),
                        ),
                      ],
                    ),
                  ),
                ),
              )
            else if (_results.isEmpty && _searchHistory.isNotEmpty && _searchController.text.isEmpty)
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text('Riwayat Pencarian',
                            style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant)),
                        const Spacer(),
                        TextButton(
                          onPressed: () async {
                            final prefs = await SharedPreferences.getInstance();
                            await prefs.setStringList('search_history_v2', []);
                            if (mounted) setState(() => _searchHistory = []);
                          },
                          child: Text('Hapus Semua',
                              style: textTheme.labelSmall?.copyWith(color: AppColors.error)),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppDimensions.spacingSm),
                    Expanded(
                      child: ListView.builder(
                        itemCount: _searchHistory.length,
                        itemBuilder: (_, i) {
                          final item = _searchHistory[i];
                          final query = item['query'] as String? ?? '';
                          final time = item['time'] as String? ?? '';
                          final timeLabel = _formatHistoryTime(time);
                          return ListTile(
                            dense: true,
                            leading: const Icon(Icons.history, size: 20, color: AppColors.onSurfaceVariant),
                            title: Text(query, style: textTheme.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                            subtitle: timeLabel.isNotEmpty
                                ? Text(timeLabel, style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant))
                                : null,
                            trailing: IconButton(
                              icon: const Icon(Icons.close, size: 16),
                              onPressed: () async {
                                final prefs = await SharedPreferences.getInstance();
                                final raw = prefs.getStringList('search_history_v2') ?? [];
                                raw.removeWhere((e) => e.startsWith('$query|||'));
                                await prefs.setStringList('search_history_v2', raw);
                                if (mounted) {
                                  setState(() => _searchHistory.removeAt(i));
                                }
                              },
                            ),
                            onTap: () {
                              _searchController.text = query;
                              _search(query);
                            },
                          );
                        },
                      ),
                    ),
                  ],
                ),
              )
            else if (_results.isEmpty)
              Expanded(
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.radio_button_unchecked_outlined, size: 64,
                          color: AppColors.onSurfaceVariant.withValues(alpha: 0.4)),
                      const SizedBox(height: AppDimensions.spacingMd),
                      Text('Masukkan judul atau URL untuk mencari',
                          style: textTheme.bodyLarge?.copyWith(color: AppColors.onSurfaceVariant)),
                      Text('Contoh: "One Piece" atau "https://...chapter-1"',
                          style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                    ],
                  ),
                ),
              )
            else
              Expanded(
                child: RefreshIndicator(
                  onRefresh: () => _search(_searchController.text.trim()),
                  child: ListView.builder(
                    itemCount: _results.length +
                        (_results.length > 10 ? 1 : 0),
                    itemBuilder: (_, i) {
                      if (i == _results.length) {
                        return Padding(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          child: Center(
                            child: Text('${_results.length} hasil ditemukan',
                                style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                          ),
                        );
                      }
                      final series = _results[i];
                      return Card(
                        margin: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
                        child: ListTile(
                          leading: ClipRRect(
                            borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                            child: series.thumbnailUrl != null
                                ? Image.network(
                                    series.thumbnailUrl!,
                                    width: 48, height: 64,
                                    fit: BoxFit.cover,
                                    errorBuilder: (_, __, ___) => Container(
                                      width: 48, height: 64,
                                      color: AppColors.surfaceContainerHigh,
                                      child: const Icon(Icons.image_outlined),
                                    ),
                                  )
                                : Container(
                                    width: 48, height: 64,
                                    color: AppColors.surfaceContainerHigh,
                                    child: const Icon(Icons.image_outlined),
                                  ),
                          ),
                          title: Text(series.title, maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text(series.adapterName),
                          trailing: Text('${series.chapterCount ?? '?'} ch',
                              style: textTheme.bodySmall?.copyWith(color: AppColors.onSurfaceVariant)),
                          onTap: () => context.push('/series/${Uri.encodeComponent(series.url)}'),
                        ),
                      );
                    },
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}