import os
import re
import sys
from collections import Counter
from PIL import Image, UnidentifiedImageError

# ================== KONFIG ==================
WIDTH_TOLERANCE = 5
CONFIRM_RUN = 3              # Minimal streak body dari belakang
ASPECT_PERCENTILE = 0.25
HEADER_IGNORE = 5            # Abaikan N gambar pertama saat hitung Body Width

_NATURAL_SORT_REGEX = re.compile(r'(\d+)')


def natural_sort_key(s: str):
    name = os.path.splitext(s)[0]
    parts = _NATURAL_SORT_REGEX.split(name)
    key = []
    for p in parts:
        key.append(int(p) if p.isdigit() else p.lower())
    return key


def _read_dimensions(root, images):
    entries = []
    for file in images:
        full_path = os.path.join(root, file)
        try:
            with Image.open(full_path) as img:
                w, h = img.size
            entries.append((file, w, h, os.path.getsize(full_path)))
        except Exception as e:
            print(f"⚠️ Gagal baca {file}: {e}")
            entries.append((file, None, None, None))
    return entries


def compute_reference_width(entries, header_ignore=HEADER_IGNORE):
    """Body Width = width paling sering setelah melewati header awal."""
    if len(entries) <= header_ignore:
        counts = Counter(w for _, w, _, _ in entries if w is not None)
    else:
        counts = Counter(w for _, w, _, _ in entries[header_ignore:] if w is not None)
    return counts.most_common(1)[0][0] if counts else None


def compute_min_aspect_threshold(entries, body_width):
    aspects = []
    for _, w, h, _ in entries:
        if w and h and w > 0 and abs(w - body_width) <= WIDTH_TOLERANCE:
            aspects.append(h / w)
    if not aspects:
        return 0.0
    aspects.sort()
    idx = min(int(len(aspects) * ASPECT_PERCENTILE), len(aspects) - 1)
    return aspects[idx]


def is_body_page(w, h, body_width, min_aspect):
    if not w or not h or w == 0:
        return False
    if abs(w - body_width) > WIDTH_TOLERANCE:
        return False
    return (h / w) >= min_aspect


def detect_body_start(entries, body_width, min_aspect):
    for i, (_, w, h, _) in enumerate(entries):
        if is_body_page(w, h, body_width, min_aspect):
            return i
    return None


def find_banner_start(entries, body_start_idx, body_width, min_aspect):
    """Scan dari belakang, cari streak body terakhir."""
    if body_start_idx is None or not entries:
        return len(entries)

    streak = 0
    banner_start_idx = len(entries)   # default: tidak hapus apa-apa

    for i in range(len(entries) - 1, body_start_idx - 1, -1):
        _, w, h, _ = entries[i]
        if is_body_page(w, h, body_width, min_aspect):
            streak += 1
            if streak >= CONFIRM_RUN:
                banner_start_idx = i + 1          # Hapus mulai setelah streak ini
                break
        else:
            streak = 0

    # Jika tidak ada streak yang cukup kuat di belakang, hapus dari body_start
    if banner_start_idx == len(entries) and body_start_idx is not None:
        banner_start_idx = body_start_idx

    return banner_start_idx


def delete_end_banner(root, entries, banner_start_idx, dry_run=False):
    to_delete = entries[banner_start_idx:]
    if not to_delete:
        return 0

    first = to_delete[0]
    print(f"🚩 Banner mulai dari: {first[0]} ({first[1]}x{first[2]})")

    deleted = 0
    for file, _, _, _ in to_delete:
        path = os.path.join(root, file)
        if dry_run:
            print(f"[DRY-RUN] Akan dihapus → {file}")
            deleted += 1
            continue
        try:
            os.remove(path)
            print(f"🗑️ Dihapus → {file}")
            deleted += 1
        except Exception as e:
            print(f"❌ Gagal: {file} ({e})")
    return deleted


def clean_directory(target_path, dry_run=False, show_table=False):
    if not os.path.isdir(target_path):
        print("❌ Folder tidak ditemukan!")
        return

    image_exts = {'.jpg', '.jpeg', '.png', '.webp'}
    total_deleted = 0

    for root, _, files in os.walk(target_path):
        images = [f for f in files if os.path.splitext(f)[1].lower() in image_exts]
        if not images:
            continue

        images.sort(key=natural_sort_key)
        entries = _read_dimensions(root, images)

        body_width = compute_reference_width(entries)
        if not body_width:
            print(f"⏭️ Lewati {root} (tidak ada gambar valid)")
            continue

        min_aspect = compute_min_aspect_threshold(entries, body_width)
        print(f"\n📁 {root}")
        print(f"Body Width terdeteksi: {body_width}px | Min Aspect: {min_aspect:.3f}")

        body_start_idx = detect_body_start(entries, body_width, min_aspect)
        if body_start_idx is None:
            print("⏭️ Tidak ditemukan halaman body.")
            continue

        banner_start_idx = find_banner_start(entries, body_start_idx, body_width, min_aspect)

        if show_table:
            print("\n=== TABEL DIAGNOSTIK ===")
            for i, (f, w, h, _) in enumerate(entries):
                status = "HAPUS" if i >= banner_start_idx else "SIMPAN"
                aspect = f"{h/w:.2f}" if w and h else "-"
                print(f"{i:3d} | {f:<20} | {w:4} | {h:4} | {aspect:>6} | {status}")

        deleted = delete_end_banner(root, entries, banner_start_idx, dry_run)
        total_deleted += deleted

    print(f"\n✅ SELESAI! Total file dihapus: {total_deleted}")


if __name__ == "__main__":
    print("=== Comic Image Cleaner v3 (Logic Updated) ===\n")

    if len(sys.argv) > 1:
        path = sys.argv[1].strip('"\'')
        dry_run = "--dry-run" in sys.argv
        show_table = "--table" in sys.argv
    else:
        path = input("Masukkan path folder: ").strip('"\'')
        dry_run = input("Dry Run? (y/N): ").strip().lower() == 'y'
        show_table = input("Tampilkan tabel? (y/N): ").strip().lower() == 'y'

    clean_directory(path, dry_run=dry_run, show_table=show_table)