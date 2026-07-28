import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:comic_downloader/app.dart';

void main() {
  testWidgets('App loads without crash', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: ComicDownloaderApp()));
    expect(find.byType(ComicDownloaderApp), findsOneWidget);
  });
}
