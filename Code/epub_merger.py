import os
import re
import shutil
import zipfile
import uuid
from collections import defaultdict
from lxml import etree


SOURCE_DIR = r"D:\zayn\comic_downloader\folder"
OUTPUT_DIR = r"D:\zayn\comic_downloader\Result"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def numeric_sort_key(name):
    numbers = re.findall(r'\d+', name)
    return [int(n) for n in numbers] if numbers else [float('inf')]


def get_base_name(filename):
    """
    Strip extension, bracket tags like _[epub], then trailing number block.
    'One Piece 01_[epub].epub'   -> 'One Piece'
    'naruto_ch_003.epub'         -> 'naruto_ch'
    'some title 7.epub'          -> 'some title'
    """
    name = os.path.splitext(filename)[0]
    # Remove bracket/paren tags anywhere in the name: _[epub], (v2), [EN], etc.
    name = re.sub(r'[\s_\-]*[\(\[][^\)\]]*[\)\]]', '', name).strip()
    # Strip trailing number block with optional separators before it
    base = re.sub(r'[\s_\-\.]+\d+\s*$', '', name).strip()
    return base if base else name


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


# ─── Grouping ─────────────────────────────────────────────────────────────────

def group_epubs(source_dir):
    if not os.path.isdir(source_dir):
        print(f"❌ Source directory not found: {source_dir}")
        return {}

    groups = defaultdict(list)

    for entry in os.scandir(source_dir):
        if entry.is_file() and entry.name.lower().endswith('.epub'):
            base = get_base_name(entry.name)
            groups[base].append(entry.path)

    for base in groups:
        groups[base].sort(key=lambda p: numeric_sort_key(os.path.basename(p)))

    return dict(groups)


# ─── EPUB Merging ─────────────────────────────────────────────────────────────

NS = {
    'opf': 'http://www.idpf.org/2007/opf',
    'dc':  'http://purl.org/dc/elements/1.1/',
    'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'epub': 'http://www.idpf.org/2007/ops',
}

OPF_NS   = 'http://www.idpf.org/2007/opf'
DC_NS    = 'http://purl.org/dc/elements/1.1/'
NCX_NS   = 'http://www.daisy.org/z3986/2005/ncx/'
XHTML_NS = 'http://www.w3.org/1999/xhtml'


def find_opf_path(zf):
    """Read META-INF/container.xml to find the OPF rootfile."""
    container_xml = zf.read('META-INF/container.xml')
    root = etree.fromstring(container_xml)
    rootfile = root.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
    if rootfile is None:
        # Try without namespace
        rootfile = root.find('.//rootfile')
    return rootfile.get('full-path')


def parse_opf(zf, opf_path):
    opf_xml = zf.read(opf_path)
    return etree.fromstring(opf_xml), os.path.dirname(opf_path)


def merge_epubs(epub_paths, output_path, title):
    """
    Merge multiple EPUB files into one.
    Strategy: unpack all EPUBs into a flat structure, rewrite OPF and NCX.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Collect all content from each epub
    all_manifest_items = []   # list of dicts: {id, href, media_type, content}
    all_spine_idrefs    = []   # ordered list of manifest IDs for the spine
    all_ncx_navpoints   = []   # list of (label, src) for TOC
    book_title          = title

    used_ids    = set()
    used_hrefs  = set()

    def unique_id(candidate):
        base = re.sub(r'[^a-zA-Z0-9_\-]', '_', candidate)
        if base not in used_ids:
            used_ids.add(base)
            return base
        i = 2
        while f"{base}_{i}" in used_ids:
            i += 1
        uid = f"{base}_{i}"
        used_ids.add(uid)
        return uid

    def unique_href(candidate):
        if candidate not in used_hrefs:
            used_hrefs.add(candidate)
            return candidate
        name, ext = os.path.splitext(candidate)
        i = 2
        while f"{name}_{i}{ext}" in used_hrefs:
            i += 1
        href = f"{name}_{i}{ext}"
        used_hrefs.add(href)
        return href

    vol_index = 0

    for epub_path in epub_paths:
        vol_index += 1
        epub_name = os.path.splitext(os.path.basename(epub_path))[0]
        print(f"  📖 Reading: {os.path.basename(epub_path)}")

        try:
            with zipfile.ZipFile(epub_path, 'r') as zf:
                opf_path  = find_opf_path(zf)
                opf_root, opf_dir = parse_opf(zf, opf_path)

                # Read title from first volume if not overridden
                dc_title = opf_root.find(f'.//{{{DC_NS}}}title')
                if dc_title is not None and vol_index == 1:
                    book_title = dc_title.text or title

                # Build id->item map from manifest
                manifest = opf_root.find(f'{{{OPF_NS}}}manifest')
                spine    = opf_root.find(f'{{{OPF_NS}}}spine')

                id_to_item = {}
                if manifest is not None:
                    for item in manifest:
                        iid   = item.get('id', '')
                        ihref = item.get('href', '')
                        itype = item.get('media-type', '')
                        id_to_item[iid] = {'href': ihref, 'media_type': itype}

                # Get NCX id from spine toc attribute
                ncx_id = spine.get('toc', '') if spine is not None else ''

                # Read NCX navpoints
                ncx_item = id_to_item.get(ncx_id, {})
                ncx_href = ncx_item.get('href', '')
                ncx_full = os.path.join(opf_dir, ncx_href).replace('\\', '/') if ncx_href else ''
                navpoints = []
                if ncx_full and ncx_full in zf.namelist():
                    ncx_xml  = zf.read(ncx_full)
                    ncx_root = etree.fromstring(ncx_xml)
                    for np in ncx_root.findall(f'.//{{{NCX_NS}}}navPoint'):
                        label_el = np.find(f'.//{{{NCX_NS}}}text')
                        content_el = np.find(f'{{{NCX_NS}}}content')
                        if label_el is not None and content_el is not None:
                            navpoints.append((
                                label_el.text or '',
                                content_el.get('src', '')
                            ))

                # Collect spine idrefs (ordered)
                spine_idrefs = []
                if spine is not None:
                    for itemref in spine:
                        spine_idrefs.append(itemref.get('idref', ''))

                # Read all manifest items and their binary content
                vol_prefix = f"v{vol_index:02d}_"
                item_id_map = {}   # old id -> new id

                for iid, item_info in id_to_item.items():
                    old_href   = item_info['href']
                    media_type = item_info['media_type']

                    # Build full path inside zip
                    if opf_dir:
                        zip_path = opf_dir + '/' + old_href
                    else:
                        zip_path = old_href

                    # Normalize
                    zip_path = os.path.normpath(zip_path).replace('\\', '/')

                    content = None
                    if zip_path in zf.namelist():
                        content = zf.read(zip_path)
                    else:
                        # Try alternate paths
                        for name in zf.namelist():
                            if name.endswith('/' + old_href) or name == old_href:
                                content = zf.read(name)
                                break

                    if content is None:
                        continue

                    # Assign unique new id and href
                    new_id   = unique_id(vol_prefix + iid)
                    new_href = unique_href(vol_prefix + os.path.basename(old_href))
                    item_id_map[iid] = new_id

                    all_manifest_items.append({
                        'id':         new_id,
                        'href':       new_href,
                        'media_type': media_type,
                        'content':    content,
                        'is_ncx':     (iid == ncx_id),
                    })

                # Map spine idrefs to new ids
                for old_idref in spine_idrefs:
                    new_idref = item_id_map.get(old_idref)
                    if new_idref:
                        all_spine_idrefs.append(new_idref)

                # Map navpoints to new hrefs
                # Build old_href -> new_href map
                old_to_new_href = {}
                for iid, item_info in id_to_item.items():
                    old_href = os.path.basename(item_info['href'])
                    new_id   = item_id_map.get(iid)
                    if new_id:
                        # Find new href for this new_id
                        for mi in all_manifest_items:
                            if mi['id'] == new_id:
                                old_to_new_href[item_info['href']] = mi['href']
                                old_to_new_href[old_href]          = mi['href']
                                break

                for label, old_src in navpoints:
                    # src may have fragment: chapter.html#section
                    src_file = old_src.split('#')[0]
                    fragment = ('#' + old_src.split('#')[1]) if '#' in old_src else ''
                    new_src  = old_to_new_href.get(src_file, old_to_new_href.get(os.path.basename(src_file), old_src))
                    all_ncx_navpoints.append((label, new_src + fragment))

        except Exception as e:
            print(f"  ⚠️  Error reading {os.path.basename(epub_path)}: {e}")
            continue

    if not all_manifest_items:
        print("  ❌ No content collected. Aborting.")
        return False

    # ── Build merged EPUB ──────────────────────────────────────────────────────

    book_uid = str(uuid.uuid4())

    # Separate NCX items; we'll write a unified NCX
    non_ncx_items = [i for i in all_manifest_items if not i['is_ncx']]

    # Build unified NCX
    ncx_id   = 'ncx'
    ncx_href = 'toc.ncx'
    used_ids.add(ncx_id)
    used_hrefs.add(ncx_href)

    ncx_navpoints_xml = ''
    for idx, (label, src) in enumerate(all_ncx_navpoints, 1):
        ncx_navpoints_xml += f'''    <navPoint id="np{idx}" playOrder="{idx}">
      <navLabel><text>{_xml_escape(label)}</text></navLabel>
      <content src="{_xml_escape(src)}"/>
    </navPoint>\n'''

    ncx_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_uid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{_xml_escape(book_title)}</text></docTitle>
  <navMap>
{ncx_navpoints_xml}  </navMap>
</ncx>
'''.encode('utf-8')

    # Build OPF manifest entries
    manifest_xml = f'    <item id="{ncx_id}" href="{ncx_href}" media-type="application/x-dtbncx+xml"/>\n'
    for item in non_ncx_items:
        manifest_xml += f'    <item id="{item["id"]}" href="{item["href"]}" media-type="{item["media_type"]}"/>\n'

    # Build OPF spine entries
    spine_xml = ''
    for idref in all_spine_idrefs:
        # Only include idrefs that exist in non_ncx_items
        if any(i['id'] == idref for i in non_ncx_items):
            spine_xml += f'    <itemref idref="{idref}"/>\n'

    opf_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{_xml_escape(book_title)}</dc:title>
    <dc:identifier id="BookId">{book_uid}</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
{manifest_xml}  </manifest>
  <spine toc="{ncx_id}">
{spine_xml}  </spine>
</package>
'''.encode('utf-8')

    container_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''

    # Write ZIP
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # mimetype must be first and uncompressed
            zf.writestr(
                zipfile.ZipInfo('mimetype'),
                'application/epub+zip',
                compress_type=zipfile.ZIP_STORED
            )
            zf.writestr('META-INF/container.xml', container_xml)
            zf.writestr('OEBPS/content.opf', opf_content)
            zf.writestr('OEBPS/toc.ncx', ncx_content)

            for item in non_ncx_items:
                zf.writestr(f'OEBPS/{item["href"]}', item['content'])

        print(f"  ✅ Saved : {output_path}")
        print(f"  📄 Items : {len(non_ncx_items)} | Spine: {len(all_spine_idrefs)} | TOC entries: {len(all_ncx_navpoints)}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to write EPUB: {e}")
        return False


def _xml_escape(text):
    if not text:
        return ''
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  EPUB Multi-Volume Merger")
    print("=" * 55)
    print(f"📂 Source : {SOURCE_DIR}")
    print(f"📁 Output : {OUTPUT_DIR}")
    print()

    groups = group_epubs(SOURCE_DIR)

    if not groups:
        print("No EPUB files found in source directory.")
        return

    print(f"Found {len(groups)} group(s):\n")
    for base, files in sorted(groups.items()):
        print(f"  [{base}]  ({len(files)} file(s))")
        for f in files:
            print(f"    └─ {os.path.basename(f)}")
    print()

    choice = input("Process ALL groups? (y/n): ").strip().lower()

    if choice == 'y':
        targets = sorted(groups.items())
    else:
        names = sorted(groups.keys())
        for i, name in enumerate(names, 1):
            print(f"  {i}. {name}")
        picks = input("Enter number(s) separated by commas: ").strip()
        try:
            indices = [int(x.strip()) - 1 for x in picks.split(',')]
            targets = [(names[i], groups[names[i]]) for i in indices]
        except (ValueError, IndexError):
            print("❌ Invalid selection.")
            return

    print()
    for base_name, epub_files in targets:
        safe_name   = sanitize_filename(base_name)
        output_file = os.path.join(OUTPUT_DIR, safe_name + ".epub")

        print(f"🔄 Processing: {base_name}")
        print(f"   Volumes   : {[os.path.basename(f) for f in epub_files]}")

        if len(epub_files) == 1:
            # Single file — just copy, no merge needed
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            shutil.copy2(epub_files[0], output_file)
            print(f"  ✅ Copied (single volume): {output_file}")
        else:
            merge_epubs(epub_files, output_file, base_name)

        print()

    print("Done!")


if __name__ == "__main__":
    main()