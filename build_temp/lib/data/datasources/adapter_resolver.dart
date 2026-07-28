import '../../domain/repositories/site_adapter.dart';
import 'remote_data_source.dart';
import 'generic_site_adapter.dart';
import 'demonic_scans_adapter.dart';

BaseSiteAdapter resolveAdapter(String url, {RemoteDataSource? dataSource}) {
  final domain = Uri.tryParse(url)?.host.replaceFirst('www.', '') ?? '';

  if (domain.contains('demonicscans')) {
    return DemonicScansAdapter(dataSource: dataSource);
  }

  return GenericSiteAdapter(dataSource: dataSource);
}
