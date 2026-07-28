import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/constants/app_colors.dart';
import '../../core/constants/app_dimensions.dart';
import '../../core/utils/cleaner.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  int _parallelDownloads = 3;
  int _retryCount = 3;
  String _outputFolder = '';
  bool _cleaning = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _parallelDownloads = prefs.getInt('max_parallel') ?? 3;
      _retryCount = prefs.getInt('retry_count') ?? 3;
      _outputFolder = prefs.getString('output_folder') ?? '';
    });
  }

  Future<void> _pickFolder() async {
    final controller = TextEditingController(text: _outputFolder);
    final result = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Folder Output'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: 'Masukkan path folder',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(_), child: const Text('Batal')),
          FilledButton(
            onPressed: () => Navigator.pop(_, controller.text),
            child: const Text('Simpan'),
          ),
        ],
      ),
    );

    if (result != null && result.isNotEmpty) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('output_folder', result);
      setState(() => _outputFolder = result);
    }
  }

  Future<void> _runCleaner() async {
    if (_outputFolder.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Atur folder output dulu')),
      );
      return;
    }

    setState(() => _cleaning = true);

    try {
      final result = await ImageCleaner.cleanDirectory(_outputFolder, dryRun: false);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.totalDeleted} file sementara dihapus'),
          backgroundColor: AppColors.secondary,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Gagal: $e'), backgroundColor: AppColors.error),
      );
    } finally {
      if (mounted) setState(() => _cleaning = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Pengaturan'),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppDimensions.spacingMd),
        children: [
          _SectionHeader(title: 'Tampilan', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.palette_outlined,
            title: 'Tema',
            subtitle: 'Gelap',
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Unduhan', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.moving_outlined,
            title: 'Paralel download maks.',
            subtitle: '$_parallelDownloads',
            onTap: () => _showEditDialog(
              'Paralel Download', _parallelDownloads, (v) {
              setState(() => _parallelDownloads = v);
              SharedPreferences.getInstance().then((p) => p.setInt('max_parallel', v));
            },
            ),
          ),
          _SettingsTile(
            icon: Icons.replay_outlined,
            title: 'Retry count',
            subtitle: '$_retryCount',
            onTap: () => _showEditDialog(
              'Retry Count', _retryCount, (v) {
              setState(() => _retryCount = v);
              SharedPreferences.getInstance().then((p) => p.setInt('retry_count', v));
            },
            ),
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Penyimpanan', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.folder_outlined,
            title: 'Folder output',
            subtitle: _outputFolder.isNotEmpty ? _outputFolder : 'Atur folder penyimpanan',
            onTap: _pickFolder,
          ),
          _SettingsTile(
            icon: _cleaning ? Icons.hourglass_top : Icons.cleaning_services_outlined,
            title: 'Bersihkan File Sementara',
            subtitle: _cleaning ? 'Membersihkan...' : 'Hapus file banner/iklan sisa download',
            onTap: _cleaning ? null : _runCleaner,
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Adapter', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.language_outlined,
            title: 'Kelola Situs',
            subtitle: 'Aktifkan/nonaktifkan adapter',
            onTap: () => context.push('/settings/adapters'),
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Tentang', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.info_outline,
            title: 'Versi',
            subtitle: '1.0.0',
          ),
        ],
      ),
    );
  }

  void _showEditDialog(String title, int current, void Function(int) onSave) {
    final controller = TextEditingController(text: current.toString());
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(title),
        content: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(border: OutlineInputBorder(), hintText: 'Nilai'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(_), child: const Text('Batal')),
          FilledButton(
            onPressed: () {
              final v = int.tryParse(controller.text);
              if (v != null && v > 0) {
                onSave(v);
                Navigator.pop(_);
              }
            },
            child: const Text('Simpan'),
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
      padding: const EdgeInsets.only(bottom: AppDimensions.spacingSm),
      child: Text(title,
        style: textTheme.titleSmall?.copyWith(
          color: AppColors.primary,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _SettingsTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;
  const _SettingsTile({required this.icon, required this.title, required this.subtitle, this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppDimensions.spacingXs),
      child: ListTile(
        leading: Icon(icon, color: AppColors.primary),
        title: Text(title),
        subtitle: Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
        trailing: onTap != null ? const Icon(Icons.chevron_right) : null,
        onTap: onTap,
      ),
    );
  }
}
