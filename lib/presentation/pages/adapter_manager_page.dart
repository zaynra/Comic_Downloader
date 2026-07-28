import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';

class AdapterManagerPage extends StatefulWidget {
  const AdapterManagerPage({super.key});

  @override
  State<AdapterManagerPage> createState() => _AdapterManagerPageState();
}

class _CustomAdapter {
  String name;
  String baseUrl;
  String cssSelector;

  _CustomAdapter({
    required this.name,
    required this.baseUrl,
    this.cssSelector = '',
  });

  Map<String, dynamic> toJson() => {
    'name': name,
    'baseUrl': baseUrl,
    'cssSelector': cssSelector,
  };

  factory _CustomAdapter.fromJson(Map<String, dynamic> json) => _CustomAdapter(
    name: json['name'] as String? ?? '',
    baseUrl: json['baseUrl'] as String? ?? '',
    cssSelector: json['cssSelector'] as String? ?? '',
  );
}

class _AdapterManagerPageState extends State<AdapterManagerPage> {
  bool _genericEnabled = true;
  bool _demonicEnabled = true;
  List<_CustomAdapter> _customAdapters = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _genericEnabled = prefs.getBool('adapter_generic') ?? true;
      _demonicEnabled = prefs.getBool('adapter_demonic') ?? true;
      _customAdapters = _loadCustomAdapters(prefs);
    });
  }

  List<_CustomAdapter> _loadCustomAdapters(SharedPreferences prefs) {
    final data = prefs.getString('custom_adapters_json');
    if (data == null) return [];
    try {
      final list = jsonDecode(data) as List;
      return list.map((e) => _CustomAdapter.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> _saveCustomAdapters() async {
    final prefs = await SharedPreferences.getInstance();
    final data = jsonEncode(_customAdapters.map((a) => a.toJson()).toList());
    await prefs.setString('custom_adapters_json', data);
  }

  Future<void> _toggleGeneric(bool v) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('adapter_generic', v);
    setState(() => _genericEnabled = v);
  }

  Future<void> _toggleDemonic(bool v) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('adapter_demonic', v);
    setState(() => _demonicEnabled = v);
  }

  void _showAddAdapterDialog({int? editIndex}) {
    final existing = editIndex != null ? _customAdapters[editIndex] : null;
    final nameController = TextEditingController(text: existing?.name ?? '');
    final urlController = TextEditingController(text: existing?.baseUrl ?? '');
    final selectorController = TextEditingController(text: existing?.cssSelector ?? '');

    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(existing != null ? 'Edit Adapter' : 'Tambah Adapter Generic'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: const InputDecoration(
                labelText: 'Nama',
                hintText: 'My Site',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: AppDimensions.spacingSm),
            TextField(
              controller: urlController,
              decoration: const InputDecoration(
                labelText: 'Base URL',
                hintText: 'https://example.com',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: AppDimensions.spacingSm),
            TextField(
              controller: selectorController,
              decoration: const InputDecoration(
                labelText: 'CSS Selector (opsional)',
                hintText: 'img.chapter-page',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(_), child: const Text('Batal')),
          FilledButton(
            onPressed: () {
              if (urlController.text.trim().isEmpty || nameController.text.trim().isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Nama dan URL harus diisi')),
                );
                return;
              }
              setState(() {
                final adapter = _CustomAdapter(
                  name: nameController.text.trim(),
                  baseUrl: urlController.text.trim(),
                  cssSelector: selectorController.text.trim(),
                );
                if (editIndex != null) {
                  _customAdapters[editIndex] = adapter;
                } else {
                  _customAdapters.add(adapter);
                }
              });
              _saveCustomAdapters();
              Navigator.pop(_);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(existing != null
                    ? 'Adapter "${nameController.text.trim()}" diperbarui'
                    : 'Adapter "${nameController.text.trim()}" ditambahkan')),
              );
            },
            child: Text(existing != null ? 'Simpan' : 'Tambah'),
          ),
        ],
      ),
    );
  }

  void _deleteAdapter(int index) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Hapus Adapter?'),
        content: Text('Hapus "${_customAdapters[index].name}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(_), child: const Text('Batal')),
          FilledButton(
            onPressed: () {
              setState(() => _customAdapters.removeAt(index));
              _saveCustomAdapters();
              Navigator.pop(_);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Adapter dihapus')),
              );
            },
            style: FilledButton.styleFrom(backgroundColor: AppColors.error),
            child: const Text('Hapus'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Kelola Adapter'),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppDimensions.spacingMd),
        children: [
          _SectionHeader(title: 'Adapter Bawaan', textTheme: textTheme),
          _AdapterTile(
            name: 'Generic',
            description: 'Situs komik umum dengan selector standar',
            isActive: _genericEnabled,
            onToggle: _toggleGeneric,
          ),
          const SizedBox(height: AppDimensions.spacingSm),
          _AdapterTile(
            name: 'DemonicScans',
            description: 'Adaptor khusus demonicscans.org',
            isActive: _demonicEnabled,
            onToggle: _toggleDemonic,
          ),
          if (_customAdapters.isNotEmpty) ...[
            const SizedBox(height: AppDimensions.spacingLg),
            _SectionHeader(title: 'Adapter Kustom', textTheme: textTheme),
            ReorderableListView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: _customAdapters.length,
              onReorder: (oldI, newI) {
                setState(() {
                  if (newI > oldI) newI--;
                  final item = _customAdapters.removeAt(oldI);
                  _customAdapters.insert(newI, item);
                });
                _saveCustomAdapters();
              },
              itemBuilder: (_, i) {
                final adapter = _customAdapters[i];
                return Dismissible(
                  key: ValueKey('custom_${adapter.baseUrl}_$i'),
                  direction: DismissDirection.endToStart,
                  background: Container(
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.only(right: 16),
                    color: AppColors.error,
                    child: const Icon(Icons.delete_outline, color: Colors.white),
                  ),
                  onDismissed: (_) {
                    setState(() => _customAdapters.removeAt(i));
                    _saveCustomAdapters();
                  },
                  child: Card(
                    margin: const EdgeInsets.only(bottom: AppDimensions.spacingXs),
                    child: ListTile(
                      leading: Icon(Icons.drag_handle, color: AppColors.onSurfaceVariant),
                      title: Text(adapter.name),
                      subtitle: Text(adapter.baseUrl, maxLines: 1, overflow: TextOverflow.ellipsis),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            icon: const Icon(Icons.edit_outlined, size: 20),
                            tooltip: 'Edit',
                            onPressed: () => _showAddAdapterDialog(editIndex: i),
                          ),
                          IconButton(
                            icon: const Icon(Icons.delete_outline, size: 20),
                            tooltip: 'Hapus',
                            onPressed: () => _deleteAdapter(i),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ],
          const SizedBox(height: AppDimensions.spacingLg),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: OutlinedButton.icon(
              onPressed: () => _showAddAdapterDialog(),
              icon: const Icon(Icons.add),
              label: const Text('Tambah Adapter Generic'),
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  final TextTheme textTheme;
  const _SectionHeader({required this.title, required this.textTheme});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppDimensions.spacingSm, top: AppDimensions.spacingSm),
      child: Text(title,
        style: textTheme.titleSmall?.copyWith(
          color: AppColors.primary,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _AdapterTile extends StatelessWidget {
  final String name;
  final String description;
  final bool isActive;
  final ValueChanged<bool> onToggle;
  const _AdapterTile({required this.name, required this.description, required this.isActive, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(Icons.language_outlined,
            color: isActive ? AppColors.secondary : AppColors.onSurfaceVariant),
        title: Text(name),
        subtitle: Text(description),
        trailing: Switch(
          value: isActive,
          activeColor: AppColors.secondary,
          onChanged: onToggle,
        ),
      ),
    );
  }
}