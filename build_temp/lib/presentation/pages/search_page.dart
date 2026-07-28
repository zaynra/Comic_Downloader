import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../data/datasources/adapter_resolver.dart';
import '../../domain/models/series.dart';

final searchResultsProvider = FutureProvider.family<List<Series>, String>((ref, query) async {
  if (query.isEmpty) return [];
  final adapter = resolveAdapter(query);
  return adapter.search(query);
});

class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final _searchController = TextEditingController();
  final _focusNode = FocusNode();
  List<Series> _results = [];
  bool _isSearching = false;
  String? _error;

  @override
  void dispose() {
    _searchController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _search(String query) async {
    if (query.isEmpty) return;
    setState(() {
      _isSearching = true;
      _error = null;
    });

    try {
      final adapter = resolveAdapter(query);
      final results = await adapter.search(query);
      if (!mounted) return;
      setState(() {
        _results = results;
        if (results.isEmpty) _error = 'Tidak ada hasil untuk "$query"';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _results = [];
        _error = 'Gagal mencari: ${e.toString().length > 100 ? e.toString().substring(0, 100) : e.toString()}';
      });
    } finally {
      if (mounted) setState(() => _isSearching = false);
    }
  }

  Future<void> _openUrl(String url) async {
    if (url.trim().isEmpty) return;
    try {
      resolveAdapter(url);
      if (mounted) {
        context.push('/series/${Uri.encodeComponent(url.trim())}');
      }
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
      _search(data.text!);
    }
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
                suffixIcon: IconButton(
                  icon: const Icon(Icons.paste_outlined),
                  tooltip: 'Tempel dari clipboard',
                  onPressed: _pasteFromClipboard,
                ),
                border: const OutlineInputBorder(),
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
              ),
              textInputAction: TextInputAction.search,
              onSubmitted: _search,
            ),
            const SizedBox(height: AppDimensions.spacingSm),
            SizedBox(
              width: double.infinity,
              height: 44,
              child: OutlinedButton.icon(
                onPressed: () {
                  if (_searchController.text.trim().isNotEmpty) {
                    final url = _searchController.text.trim();
                    if (Uri.tryParse(url)?.hasScheme == true) {
                      _openUrl(url);
                    } else {
                      _search(url);
                    }
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
                      ],
                    ),
                  ),
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
                    ],
                  ),
                ),
              )
            else
              Expanded(
                child: ListView.builder(
                  itemCount: _results.length,
                  itemBuilder: (_, i) {
                    final series = _results[i];
                    return Card(
                      margin: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
                      child: ListTile(
                        leading: ClipRRect(
                          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                          child: series.thumbnailUrl != null
                              ? Image.network(
                                  series.thumbnailUrl!,
                                  width: 48,
                                  height: 64,
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
          ],
        ),
      ),
    );
  }
}
