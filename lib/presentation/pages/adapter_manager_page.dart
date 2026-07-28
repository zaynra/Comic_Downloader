import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';

class AdapterManagerPage extends StatefulWidget {
  const AdapterManagerPage({super.key});

  @override
  State<AdapterManagerPage> createState() => _AdapterManagerPageState();
}

class _AdapterManagerPageState extends State<AdapterManagerPage> {
  bool _genericEnabled = true;
  bool _demonicEnabled = true;

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
    });
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Kelola Adapter'),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppDimensions.spacingMd),
        children: [
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
          const SizedBox(height: AppDimensions.spacingLg),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: OutlinedButton.icon(
              onPressed: _showAddAdapterDialog,
              icon: const Icon(Icons.add),
              label: const Text('Tambah Adapter Generic'),
            ),
          ),
        ],
      ),
    );
  }

  void _showAddAdapterDialog() {
    final urlController = TextEditingController();
    final selectorController = TextEditingController();

    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Tambah Adapter Generic'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
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
              Navigator.pop(_);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Adapter ditambahkan')),
              );
            },
            child: const Text('Tambah'),
          ),
        ],
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
