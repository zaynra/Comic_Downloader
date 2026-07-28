List<Comparable<dynamic>> naturalSortKey(String name) {
  final parts = RegExp(r'(\d+)').allMatches(name);
  if (parts.isEmpty) return [name.toLowerCase()];

  final result = <Comparable<dynamic>>[];
  int lastEnd = 0;
  for (final m in parts) {
    if (m.start > lastEnd) {
      result.add(name.substring(lastEnd, m.start).toLowerCase());
    }
    result.add(int.parse(m.group(1)!));
    lastEnd = m.end;
  }
  if (lastEnd < name.length) {
    result.add(name.substring(lastEnd).toLowerCase());
  }
  return result;
}
