import os
import re
import io
import statistics
import concurrent.futures
from collections import defaultdict
from PIL import Image
import img2pdf
from notification_manager import TelegramNotifier

Image.MAX_IMAGE_PIXELS = None
bot = TelegramNotifier()

DEFAULT_SOURCE_DIR = r"D:\zayn\comic_downloader\source"
OUTPUT_FOLDER_CANDIDATES = ["Result", "PDF", "Output"]
RESULT_FOLDER_NAME = OUTPUT_FOLDER_CANDIDATES[0]

# =========================================================
# PARAMETER OPTIMASI JPEG & PDF
# =========================================================
IMAGE_QUALITY = 90          # Sweet spot: ukuran kecil, kualitas visual tidak turun
JPEG_SUBSAMPLING = 0        # 4:4:4 - Wajib untuk manga agar teks/arsiran tetap tajam (tidak color bleeding)
CHAPTER_PDF_PREFIX = "Chapter_"

def natural_sort_key(name):
    parts = re.split(r'(\d+)', name)
    key = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.lower())
    return key

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def extract_chapter_number(name):
    m = re.search(r'(\d+(?:\.\d+)?)', name)
    if not m:
        return None
    return float(m.group(1))

def format_chapter_label(num):
    if float(num).is_integer():
        return f"{int(num):04d}"
    integer_part, _, decimal_part = f"{num:g}".partition('.')
    return f"{int(integer_part):04d}.{decimal_part}"

def get_chapter_label(name):
    num = extract_chapter_number(name)
    if num is not None:
        return format_chapter_label(num)
    return sanitize_filename(name)

def format_chapter_pdf_filename(chapter_label):
    return f"{CHAPTER_PDF_PREFIX}{chapter_label}.pdf"

def is_image_file(filepath):
    try:
        with Image.open(filepath) as img:
            img.verify()
        return True
    except Exception:
        return False

def convert_to_rgb(image):
    if image.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        if image.mode == 'P':
            image = image.convert('RGBA')
        if image.mode in ('RGBA', 'LA'):
            background.paste(image, mask=image.split()[-1])
        else:
            background.paste(image)
        return background
    elif image.mode != 'RGB':
        return image.convert('RGB')
    return image

def compute_reference_size(image_paths):
    widths = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                widths.append(img.size[0])
        except Exception:
            continue
    if not widths:
        return None
    # OPTIMASI: Gunakan median alih-alih max() agar 1 gambar super lebar tidak merusak chapter
    return int(statistics.median(widths))

def process_single_image(img_path, ref_width):
    """
    Fungsi worker untuk diparalelkan. Membaca gambar, resize (hanya downscale),
    konversi RGB, dan mengembalikan byte array JPEG in-memory.
    """
    try:
        with Image.open(img_path) as img:
            img = convert_to_rgb(img)
            orig_w, orig_h = img.size
            
            # OPTIMASI KUALITAS: Jangan pernah upscaling. Hanya downscale gambar yang kebesaran.
            if orig_w > ref_width:
                scale = ref_width / orig_w
                new_w = ref_width
                new_h = round(orig_h * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            
            # OPTIMASI MEMORY & DISK: Simpan langsung ke memori (BytesIO), bukan ke temporary file disk
            img_byte_arr = io.BytesIO()
            img.save(
                img_byte_arr,
                format='JPEG',
                quality=IMAGE_QUALITY,
                optimize=True,
                progressive=True,
                subsampling=JPEG_SUBSAMPLING
            )
            return img_byte_arr.getvalue()
    except Exception as e:
        print(f" [x] Rusak/skip: {os.path.basename(img_path)} -> {e}")
        return None

def build_optimized_pdf(image_paths, ref_width, output_path, label):
    """
    Menggantikan build_long_strip_pdf.
    Menggunakan paralel processing dan img2pdf untuk bypass limitasi canvas 65k pixel.
    """
    if not ref_width:
        print(f" [x] Tidak bisa menentukan lebar referensi untuk '{label}'.")
        return False

    print(f" [i] Memproses {len(image_paths)} gambar ke memori secara paralel...", end="\r")
    valid_image_bytes = []
    
    # OPTIMASI CPU: Multithreading I/O dan resize operations
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # map menjamin urutan hasil tetap sama dengan urutan input image_paths
        results = executor.map(lambda p: process_single_image(p, ref_width), image_paths)
        for res in results:
            if res is not None:
                valid_image_bytes.append(res)
                
    if not valid_image_bytes:
        print(f" [x] Semua gambar gagal diproses di '{label}'.")
        return False

    print(f" [i] Membungkus {len(valid_image_bytes)} halaman ke PDF via img2pdf...   ", end="\r")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # OPTIMASI ANDROID & PDF: img2pdf menaruh gambar 1 per 1 di PDF tanpa decode ulang.
        # Sangat ringan di RAM, ukuran file kecil, dan bisa di-scroll instan di Android.
        pdf_bytes = img2pdf.convert(valid_image_bytes)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"\n Saved: {os.path.relpath(output_path, os.path.dirname(os.path.dirname(output_path)))}")
        return True
    except Exception as e:
        print(f"\n [x] Gagal menulis PDF: {e}")
        return False

CHAPTER_PREFIX_WORDS = ("chapter", "chapitre", "episode", "chap", "chp", "ep", "ch")
_NUMERIC_ONLY_PATTERN = re.compile(r'^[\s_\-]*\d+(?:\.\d+)?[\s_\-]*$')

def classify_folder_name(name):
    stripped = name.strip()
    if _NUMERIC_ONLY_PATTERN.match(stripped):
        return "numeric"
    base_title, num = extract_base_title(stripped)
    if num is None:
        return "none"
    normalized_base = re.sub(r'[\s_\-]+', '', base_title).lower()
    if normalized_base in CHAPTER_PREFIX_WORDS:
        return "numeric"
    return "merge"

def detect_processing_mode(source_dir):
    entries = [
        entry.name for entry in os.scandir(source_dir)
        if entry.is_dir() and entry.name not in OUTPUT_FOLDER_CANDIDATES
    ]
    total_folders = len(entries)
    numeric_count = 0
    merge_count = 0
    for name in entries:
        cls = classify_folder_name(name)
        if cls == "numeric":
            numeric_count += 1
        elif cls == "merge":
            merge_count += 1
    classified_count = numeric_count + merge_count
    if classified_count == 0:
        return "chapter", 0.0, 0.0, classified_count, total_folders
    numeric_score = round(100 * numeric_count / classified_count, 1)
    merge_score = round(100 * merge_count / classified_count, 1)
    mode = "merge" if merge_count > numeric_count else "chapter"
    return mode, numeric_score, merge_score, classified_count, total_folders

def scan_chapter_folders(source_dir):
    chapters = [
        entry.path for entry in os.scandir(source_dir)
        if entry.is_dir() and entry.name not in OUTPUT_FOLDER_CANDIDATES
    ]
    chapters.sort(key=lambda p: natural_sort_key(os.path.basename(p)))
    return chapters

def get_result_dir(source_dir):
    for candidate in OUTPUT_FOLDER_CANDIDATES:
        candidate_path = os.path.join(source_dir, candidate)
        if os.path.isdir(candidate_path):
            return candidate_path
    result_dir = os.path.join(source_dir, RESULT_FOLDER_NAME)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir

def get_completed_chapter_names(result_dir):
    completed = set()
    if os.path.isdir(result_dir):
        for f in os.listdir(result_dir):
            if f.lower().endswith(".pdf"):
                stem = os.path.splitext(f)[0]
                completed.add(get_chapter_label(stem))
    return completed

def collect_images_from_folder(folder):
    files = [
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f))
    ]
    image_files = [
        f for f in files
        if is_image_file(os.path.join(folder, f))
    ]
    image_files.sort(key=lambda f: natural_sort_key(f))
    return [os.path.join(folder, f) for f in image_files]

def convert_chapter_to_pdf(chapter_dir, output_path):
    chapter_name = os.path.basename(chapter_dir)
    image_paths = collect_images_from_folder(chapter_dir)
    if not image_paths:
        print(f" [!] Tidak ada gambar di '{chapter_name}', dilewati.")
        return False
    ref_width = compute_reference_size(image_paths)
    return build_optimized_pdf(image_paths, ref_width, output_path, chapter_name)

def prompt_chapter_range(chapters, completed_names):
    numbered = []
    for c in chapters:
        num = extract_chapter_number(os.path.basename(c))
        numbered.append((num, c))
    valid_nums = [n for n, _ in numbered if n is not None]
    if not valid_nums:
        print(" [!] Tidak bisa mendeteksi nomor chapter dari nama folder,")
        print(" semua chapter akan diproses.")
        return chapters
    not_done = [
        (num, path) for num, path in numbered
        if num is not None and get_chapter_label(os.path.basename(path)) not in completed_names
    ]
    default_start = min(n for n, _ in not_done) if not_done else min(valid_nums)
    default_end = max(valid_nums)
    def fmt(n):
        return f"{n:g}"
    raw_start = input(f" Mulai chapter [{fmt(default_start)}]: ").strip()
    raw_end = input(f" Sampai chapter [{fmt(default_end)}]: ").strip()
    try:
        start = float(raw_start) if raw_start else default_start
        end = float(raw_end) if raw_end else default_end
    except ValueError:
        print(" [!] Input tidak valid, memakai default.")
        start, end = default_start, default_end
    if start > end:
        start, end = end, start
    return [path for num, path in numbered if num is not None and start <= num <= end]

def print_pre_analysis_summary(source_dir, mode, numeric_score, merge_score):
    print("-" * 60)
    print("Analysis...")
    print("-" * 60)
    detected_label = "Per Chapter" if mode == "chapter" else "Multi Folder Merge"
    print(f"Detected Mode : {detected_label}")
    print(f"Numeric Score : {numeric_score:.1f}%")
    print(f"Merge Score : {merge_score:.1f}%")
    result_dir = get_result_dir(source_dir)
    output_folder_name = os.path.basename(result_dir)
    if mode == "chapter":
        chapters = scan_chapter_folders(source_dir)
        completed_names = get_completed_chapter_names(result_dir)
        completed_count = sum(
            1 for c in chapters
            if get_chapter_label(os.path.basename(c)) in completed_names
        )
        total = len(chapters)
        remaining = total - completed_count
        image_count = 0
        for c in chapters:
            try:
                image_count += sum(
                    1 for f in os.listdir(c)
                    if os.path.isfile(os.path.join(c, f))
                )
            except OSError:
                continue
        print(f"Total Chapter : {total}")
        print(f"Completed PDF : {completed_count}")
        print(f"Remaining     : {remaining}")
        print(f"Output Folder : {output_folder_name}")
        print(f"Image Count   : {image_count:,}")
    else:
        groups = group_folders_by_base_title(source_dir)
        completed_count = 0
        for base_title in groups:
            pdf_name = sanitize_filename(base_title) + ".pdf"
            if os.path.isfile(os.path.join(result_dir, pdf_name)):
                completed_count += 1
        print(f"Detected Series : {len(groups)}")
        print(f"Completed PDF   : {completed_count}")
        print(f"Remaining       : {len(groups) - completed_count}")
        print(f"Output Folder   : {output_folder_name}")
    print("-" * 60)
    print()

def _format_duration(elapsed_seconds):
    h, rem = divmod(int(elapsed_seconds), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def process_chapters(source_dir):
    chapters = scan_chapter_folders(source_dir)
    if not chapters:
        print("[!] Tidak ada folder chapter ditemukan di dalam source dir.")
        print(" Pastikan source dir langsung berisi folder-folder chapter")
        return
    result_dir = get_result_dir(source_dir)
    completed_names = get_completed_chapter_names(result_dir)
    selected_chapters = prompt_chapter_range(chapters, completed_names)
    if not selected_chapters:
        print("[!] Tidak ada chapter yang cocok dengan range yang dipilih.")
        return
    comic_title = os.path.basename(os.path.normpath(source_dir)) or source_dir
    selected_nums = [
        n for n in (extract_chapter_number(os.path.basename(c)) for c in selected_chapters)
        if n is not None
    ]
    range_start = min(selected_nums) if selected_nums else 0
    range_end = max(selected_nums) if selected_nums else 0
    run_start_time = time.time()
    try:
        bot.start(comic_title, range_start, range_end, activity="Convert")
    except Exception as e:
        print(f" [!] Gagal mengirim notifikasi Telegram (start): {e}")
        
    success_count = 0
    failed_count = 0
    skipped_count = 0
    print()
    for chapter_dir in selected_chapters:
        chapter_name = os.path.basename(chapter_dir)
        chapter_label = get_chapter_label(chapter_name)
        chapter_num = extract_chapter_number(chapter_name)
        if chapter_label in completed_names:
            print(f"[skip] {chapter_name} (PDF sudah ada)")
            skipped_count += 1
            continue
        output_path = os.path.join(result_dir, format_chapter_pdf_filename(chapter_label))
        print(f"Processing: {chapter_name}")
        try:
            ok = convert_chapter_to_pdf(chapter_dir, output_path)
        except Exception as e:
            print(f" [x] Error tak terduga saat memproses '{chapter_name}': {e}")
            ok = False
            try:
                bot.error(chapter_num if chapter_num is not None else chapter_name, str(e), activity="Convert", comic=comic_title)
            except Exception:
                pass
        if ok:
            success_count += 1
        else:
            failed_count += 1
            try:
                bot.error(chapter_num if chapter_num is not None else chapter_name, "Gagal membuat PDF", activity="Convert", comic=comic_title)
            except Exception:
                pass
        print()
        
    durasi = _format_duration(time.time() - run_start_time)
    total_processed = success_count + failed_count
    try:
        bot.finish(comic_title, total_processed, success_count, failed_count, durasi, activity="Convert")
    except Exception:
        pass
    print("Selesai.")
    print(f"Berhasil : {success_count}")
    print(f"Gagal    : {failed_count}")
    if skipped_count:
        print(f"Dilewati : {skipped_count} (PDF sudah ada sebelumnya)")

BASE_TITLE_PATTERN = re.compile(r'^(.*?)[\s_\-]*(\d+)$')

def extract_base_title(folder_name):
    m = BASE_TITLE_PATTERN.match(folder_name.strip())
    if not m or not m.group(1).strip():
        return folder_name.strip(), None
    return m.group(1).strip(), int(m.group(2))

def group_folders_by_base_title(source_dir):
    groups = defaultdict(list)
    for entry in os.scandir(source_dir):
        if not entry.is_dir() or entry.name in OUTPUT_FOLDER_CANDIDATES:
            continue
        base_title, _ = extract_base_title(entry.name)
        groups[base_title].append(entry.path)
    for base_title in groups:
        groups[base_title].sort(key=lambda p: natural_sort_key(os.path.basename(p)))
    return dict(sorted(groups.items(), key=lambda kv: kv[0].lower()))

def convert_group_to_pdf(base_title, folder_list, output_path):
    all_image_paths = []
    for folder in folder_list:
        all_image_paths.extend(collect_images_from_folder(folder))
    if not all_image_paths:
        print(f" [!] Tidak ada gambar sama sekali di grup '{base_title}', dilewati.")
        return False
    ref_width = compute_reference_size(all_image_paths)
    return build_optimized_pdf(all_image_paths, ref_width, output_path, base_title)

def process_multi_folder_merge(source_dir):
    groups = group_folders_by_base_title(source_dir)
    if not groups:
        print("[!] Tidak ada folder ditemukan di dalam source dir.")
        return
    result_dir = get_result_dir(source_dir)
    print(f" Total judul (base title) ditemukan: {len(groups)}\n")
    comic_title = os.path.basename(os.path.normpath(source_dir)) or source_dir
    run_start_time = time.time()
    try:
        bot.start(comic_title, 1, len(groups), activity="Convert")
    except Exception as e:
        print(f" [!] Gagal mengirim notifikasi Telegram (start): {e}")
        
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    for base_title, folder_list in groups.items():
        pdf_name = sanitize_filename(base_title) + ".pdf"
        output_path = os.path.join(result_dir, pdf_name)
        if os.path.isfile(output_path):
            print(f"Skip {base_title} (PDF sudah ada)")
            skipped_count += 1
            continue
        folder_names = ", ".join(os.path.basename(f) for f in folder_list)
        print(f"Processing: {base_title} ({len(folder_list)} folder: {folder_names})")
        try:
            ok = convert_group_to_pdf(base_title, folder_list, output_path)
        except Exception as e:
            print(f" [x] Error tak terduga saat memproses '{base_title}': {e}")
            ok = False
            try:
                bot.error(base_title, str(e), activity="Convert", comic=comic_title)
            except Exception:
                pass
        if ok:
            success_count += 1
        else:
            failed_count += 1
            try:
                bot.error(base_title, "Gagal membuat PDF untuk grup ini", activity="Convert", comic=comic_title)
            except Exception:
                pass
        print()
        
    durasi = _format_duration(time.time() - run_start_time)
    total_processed = success_count + failed_count
    try:
        bot.finish(comic_title, total_processed, success_count, failed_count, durasi, activity="Convert")
    except Exception:
        pass
    print("Selesai.")
    print(f"Berhasil : {success_count}")
    print(f"Gagal    : {failed_count}")
    if skipped_count:
        print(f"Dilewati : {skipped_count} (PDF sudah ada sebelumnya)")

def prompt_source_dir():
    while True:
        raw = input(
            f"Masukkan alamat folder source (Enter untuk default: {DEFAULT_SOURCE_DIR}): "
        ).strip()
        if raw == "":
            path = DEFAULT_SOURCE_DIR
        elif raw.lower() == "q":
            return None
        else:
            path = raw.strip('"').strip("'")
        path = os.path.normpath(path)
        if os.path.isdir(path):
            return path
        print(f"[!] Folder tidak ditemukan: {path}")
        print(" Coba lagi, atau ketik 'q' untuk keluar.\n")

def main():
    print("=" * 60)
    print(" Comic Folder -> PDF Converter (Optimized Mode)")
    print("=" * 60)
    source_dir = prompt_source_dir()
    if source_dir is None:
        print("Dibatalkan oleh user.")
        return
    print(f"\nSource: {source_dir}\n")
    mode, numeric_score, merge_score, classified_count, total_folders = detect_processing_mode(source_dir)
    print_pre_analysis_summary(source_dir, mode, numeric_score, merge_score)
    
    if mode == "merge":
        process_multi_folder_merge(source_dir)
    else:
        process_chapters(source_dir)
    print("Semua proses selesai!")

if __name__ == "__main__":
    main()

