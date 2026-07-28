import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:file_picker/file_picker.dart';
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
  String? _cleanResult;

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
    final result = await FilePicker.platform.getDirectoryPath(
      dialogTitle: 'Pilih folder penyimpanan output',
    );
    if (result != null && result.isNotEmpty) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('output_folder', result);
      setState(() => _outputFolder = result);
    }
  }

  Future<void> _openFolder() async {
    if (_outputFolder.isEmpty) return;
    try {
      await Process.run('explorer', [_outputFolder]);
    } catch (_) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Tidak bisa membuka folder: $_outputFolder')),
      );
    }
  }

  Future<void> _runCleaner() async {
    if (_outputFolder.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Atur folder output dulu')),
      );
      return;
    }

    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Bersihkan File Sementara?'),
        content: Text(
          'Tindakan ini akan menghapus file banner/iklan dari folder:\n'
          '$_outputFolder\n\n'
          'File chapter tidak akan dihapus. Lanjutkan?'
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Batal')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Bersihkan')),
        ],
      ),
    );
    if (confirm != true) return;

    setState(() { _cleaning = true; _cleanResult = null; });

    try {
      final result = await ImageCleaner.cleanDirectory(_outputFolder, dryRun: false);
      if (!mounted) return;
      setState(() {
        _cleanResult = '${result.totalDeleted} file sementara dihapus';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.totalDeleted} file dihapus'),
          backgroundColor: AppColors.secondary,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() { _cleanResult = 'Gagal: ${e.toString().length > 80 ? e.toString().substring(0, 80) : e.toString()}'; });
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
            subtitle: 'Gelap (Material 3)',
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Unduhan', textTheme: textTheme),
          _SettingsTile(
            icon: Icons.moving_outlined,
            title: 'Paralel download maks.',
            subtitle: '$_parallelDownloads',
            onTap: () => _showSliderDialog(
              'Paralel Download', _parallelDownloads, 1, 10,
              (v) {
                setState(() => _parallelDownloads = v);
                SharedPreferences.getInstance().then((p) => p.setInt('max_parallel', v));
              },
            ),
          ),
          _SettingsTile(
            icon: Icons.replay_outlined,
            title: 'Retry count',
            subtitle: '$_retryCount',
            onTap: () => _showSliderDialog(
              'Retry Count', _retryCount, 0, 10,
              (v) {
                setState(() => _retryCount = v);
                SharedPreferences.getInstance().then((p) => p.setInt('retry_count', v));
              },
            ),
          ),
          const SizedBox(height: AppDimensions.spacingLg),
          _SectionHeader(title: 'Penyimpanan', textTheme: textTheme),
          Card(
            margin: const EdgeInsets.only(bottom: AppDimensions.spacingXs),
            child: ListTile(
              leading: const Icon(Icons.folder_outlined, color: AppColors.primary),
              title: const Text('Folder output'),
              subtitle: Text(
                _outputFolder.isNotEmpty
                    ? (_outputFolder.length > 50
                        ? '...${_outputFolder.substring(_outputFolder.length - 50)}'
                        : _outputFolder)
                    : 'Atur folder penyimpanan',
                maxLines: 2, overflow: TextOverflow.ellipsis,
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_outputFolder.isNotEmpty)
                    IconButton(
                      icon: const Icon(Icons.folder_open_outlined, size: 20),
                      tooltip: 'Buka folder',
                      onPressed: _openFolder,
                    ),
                  IconButton(
                    icon: const Icon(Icons.edit_outlined, size: 20),
                    tooltip: 'Pilih folder',
                    onPressed: _pickFolder,
                  ),
                ],
              ),
              onTap: _pickFolder,
            ),
          ),
          if (_outputFolder.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 16, bottom: 4, top: 4),
              child: Text('Folder: $_outputFolder',
                  style: textTheme.labelSmall?.copyWith(color: AppColors.onSurfaceVariant)),
            ),
          _SettingsTile(
            icon: _cleaning ? Icons.hourglass_top : Icons.cleaning_services_outlined,
            title: 'Bersihkan File Sementara',
            subtitle: _cleaning
                ? 'Membersihkan...'
                : (_cleanResult ?? 'Hapus file banner/iklan sisa download'),
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
          _SettingsTile(icon: Icons.info_outline, title: 'Versi', subtitle: '1.0.0'),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  void _showSliderDialog(String title, int current, int min, int max, void Function(int) onSave) {
    double val = current.toDouble();
    showDialog(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(title),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Nilai: ${val.toInt()}', style: Theme.of(ctx).textTheme.headlineMedium),
              const SizedBox(height: 16),
              Slider(
                value: val,
                min: min.toDouble(),
                max: max.toDouble(),
                divisions: max - min,
                activeColor: AppColors.primary,
                label: val.toInt().toString(),
                onChanged: (v) => setDialogState(() => val = v),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Batal')),
            FilledButton(
              onPressed: () { onSave(val.toInt()); Navigator.pop(ctx); },
              child: const Text('Simpan'),
            ),
          ],
        ),
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
        subtitle: Text(subtitle, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: onTap != null ? const Icon(Icons.chevron_right) : null,
        onTap: onTap,
      ),
    );
  }
}