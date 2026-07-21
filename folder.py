import os
import re
import shutil
import tempfile
import time
from collections import defaultdict, Counter

from PIL import Image
from pypdf import PdfWriter
from notification_manager import TelegramNotifier

Image.MAX_IMAGE_PIXELS = None

bot = TelegramNotifier()

DEFAULT_SOURCE_DIR = r"D:\zayn\comic_downloader\source"

OUTPUT_FOLDER_CANDIDATES = ["Result", "PDF", "Output"]
RESULT_FOLDER_NAME = OUTPUT_FOLDER_CANDIDATES[0]

IMAGE_RESOLUTION = 300.0
IMAGE_QUALITY = 95          # kualitas JPEG maksimum untuk kanvas berukuran wajar
JPEG_SUBSAMPLING = 2        # 4:2:0 -- rasio kompresi terbaik, aman untuk komik/manga
JPEG_MIN_QUALITY = 82       # batas bawah adaptif, dijaga tetap tak terlihat turun


def _adaptive_jpeg_quality(width, height):
    """
    Turunkan kualitas JPEG secara halus untuk kanvas long-strip yang
    sangat besar (puluhan ribu piksel tinggi) -- di resolusi setinggi
    itu penurunan quality nyaris tidak terlihat tapi menghemat ukuran
    file signifikan. Kanvas berukuran wajar tetap memakai IMAGE_QUALITY
    penuh. Rentang dijaga sempit (82-95) supaya tidak ada penurunan
    kualitas visual yang terlihat -- kombinasi utama penghematan ukuran
    tetap datang dari optimize+progressive+subsampling di JPEG encoder,
    bukan dari quality drop ini.
    """
    megapixels = (width * height) / 1_000_000
    if megapixels > 150:
        return JPEG_MIN_QUALITY
    if megapixels > 60:
        return 86
    if megapixels > 20:
        return 90
    return IMAGE_QUALITY


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


def normalize_to_reference(image, ref_width):
    orig_w, orig_h = image.size
    scale = ref_width / orig_w
    new_w = ref_width
    new_h = round(orig_h * scale)

    return image.resize((new_w, new_h), Image.LANCZOS)


def compute_reference_size(image_paths):
    """
    PENTING (fix pembengkakan ukuran PDF):

    Sebelumnya fungsi ini memakai max(widths) sebagai lebar acuan.
    Masalahnya: kalau ada SATU gambar "outlier" di dalam chapter yang
    lebarnya jauh di atas mayoritas (mis. halaman kredit, iklan,
    double-spread, atau scan beda sumber), maka SEMUA gambar lain
    di-upscale (LANCZOS) mengikuti lebar outlier itu. Upscaling
    memperbesar jumlah piksel setiap halaman berkali-kali lipat tanpa
    menambah detail asli apa pun -- hasilnya data JPEG jadi jauh lebih
    "berisik" secara statistik dan ukuran file bisa melonjak 3-10x
    lipat dari wajarnya. Ini persis pola bug yang dilaporkan: mayoritas
    chapter normal, tapi sesekali ada yang meledak ke 150-200 MB.

    Fix: pakai lebar yang PALING SERING MUNCUL (mode), bukan yang
    terbesar. Mayoritas halaman dalam satu chapter biasanya berasal
    dari scan/sumber yang sama dengan lebar konsisten, jadi mode adalah
    representasi "ukuran normal" yang jauh lebih aman. Efeknya:
    - Gambar-gambar mayoritas TIDAK di-upscale sama sekali (tetap di
      resolusi asli mereka -- kualitas baca di Moon+ Reader dkk tidak
      berubah).
    - Outlier yang jarang muncul justru di-DOWNSCALE mengikuti
      mayoritas, yang aman untuk ukuran file (downscale tidak pernah
      menambah data, hanya mengurangi).
    - Kalau ada beberapa lebar yang sama-sama paling sering muncul
      (jarang terjadi), pakai median seluruh lebar sebagai tie-breaker
      supaya hasil tetap stabil dan tidak condong ke ekstrem.
    """
    widths = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                widths.append(img.size[0])
        except Exception:
            continue

    if not widths:
        return None

    counts = Counter(widths)
    max_count = max(counts.values())
    candidates = sorted(w for w, c in counts.items() if c == max_count)

    if len(candidates) == 1:
        return candidates[0]

    sorted_widths = sorted(widths)
    n = len(sorted_widths)
    if n % 2 == 1:
        median_width = sorted_widths[n // 2]
    else:
        median_width = (sorted_widths[n // 2 - 1] + sorted_widths[n // 2]) // 2

    return min(candidates, key=lambda w: abs(w - median_width))


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


MAX_PDF_PAGE_HEIGHT = 65000


def _compute_scaled_heights(image_paths, ref_width):
    valid_paths = []
    heights = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                orig_w, orig_h = img.size
            scale = ref_width / orig_w
            new_h = round(orig_h * scale)
            valid_paths.append(path)
            heights.append(new_h)
        except Exception as e:
            print(f"      [x] Rusak/skip: {os.path.basename(path)} -> {e}")

    total_height = sum(heights)
    return valid_paths, heights, total_height


def _chunk_by_height(paths, heights, max_height):
    chunks = []
    cur_paths, cur_heights, cur_total = [], [], 0

    for p, h in zip(paths, heights):
        if h >= max_height:
            if cur_paths:
                chunks.append((cur_paths, cur_heights))
                cur_paths, cur_heights, cur_total = [], [], 0
            chunks.append(([p], [h]))
            continue

        if cur_paths and cur_total + h > max_height:
            chunks.append((cur_paths, cur_heights))
            cur_paths, cur_heights, cur_total = [], [], 0

        cur_paths.append(p)
        cur_heights.append(h)
        cur_total += h

    if cur_paths:
        chunks.append((cur_paths, cur_heights))

    return chunks


def _paste_chunk_canvas(paths, heights, ref_width, max_height, start_index, total_count):
    total_height = sum(heights)
    use_width = ref_width
    use_heights = heights

    if total_height > max_height:
        scale = max_height / total_height
        use_width = max(1, int(ref_width * scale))
        use_heights = [max(1, round(h * scale)) for h in heights]
        total_height = sum(use_heights)
        print("      [!] Satu gambar terlalu tinggi untuk 1 halaman PDF, diskalakan turun agar muat.")

    canvas = Image.new("RGB", (use_width, total_height), (255, 255, 255))

    y = 0
    pasted = 0
    for i, (img_path, h) in enumerate(zip(paths, use_heights), 1):
        print(f"   Page: {start_index + i}/{total_count}", end="\r")

        img = None
        try:
            img = Image.open(img_path)
            img = convert_to_rgb(img)
            img = normalize_to_reference(img, use_width)
            canvas.paste(img, (0, y))
            y += img.height
            pasted += 1
        except Exception as e:
            print(f"      [x] Rusak/skip saat menempel: {os.path.basename(img_path)} -> {e}")
            y += h
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass

    return canvas, pasted


def _merge_pdfs(temp_pdf_paths, output_path):
    writer = PdfWriter()
    try:
        for temp_path in temp_pdf_paths:
            writer.append(temp_path)

        # Kompres content stream (operator gambar per halaman, bukan data
        # JPEG-nya) -- object stream jadi lebih ringkas. Tidak mengubah
        # tampilan/isi halaman sama sekali, murni housekeeping PDF.
        try:
            writer.compress_content_streams()
        except Exception:
            pass  # aman diabaikan kalau versi pypdf tidak punya method ini

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        return True
    except Exception as e:
        print(f"   [x] Gagal menulis PDF: {e}")
        return False
    finally:
        writer.close()


def build_long_strip_pdf(image_paths, ref_width, output_path, label):
    total_pages = len(image_paths)

    if not ref_width:
        print(f"   [x] Tidak bisa menentukan lebar referensi untuk '{label}'.")
        return False

    valid_paths, heights, total_height = _compute_scaled_heights(image_paths, ref_width)

    if not valid_paths or total_height <= 0:
        print(f"   [x] Semua gambar gagal diproses di '{label}'.")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if total_height <= MAX_PDF_PAGE_HEIGHT:
        canvas, pasted = _paste_chunk_canvas(
            valid_paths, heights, ref_width, MAX_PDF_PAGE_HEIGHT, 0, len(valid_paths)
        )
        print()

        success = True
        try:
            canvas.save(
                output_path,
                "PDF",
                resolution=IMAGE_RESOLUTION,
                quality=_adaptive_jpeg_quality(*canvas.size),
                optimize=True,
                progressive=True,
                subsampling=JPEG_SUBSAMPLING,
            )
        except Exception as e:
            print(f"   [x] Gagal menulis PDF: {e}")
            success = False
        finally:
            canvas.close()

        if success:
            print(f"   Saved: {os.path.relpath(output_path, os.path.dirname(os.path.dirname(output_path)))}")
            print(f"   Pages saved: {pasted}/{total_pages}")

        return success

    chunks = _chunk_by_height(valid_paths, heights, MAX_PDF_PAGE_HEIGHT)
    print(f"   [i] '{label}' sangat panjang (~{total_height}px > batas PDF {MAX_PDF_PAGE_HEIGHT}px),")
    print(f"       dipecah jadi {len(chunks)} halaman PDF (bukan {total_pages} halaman seperti dulu).")

    with tempfile.TemporaryDirectory(prefix="comic_pdf_super_") as temp_dir:
        temp_pdf_paths = []
        pasted_total = 0
        idx_offset = 0

        for ci, (paths_chunk, heights_chunk) in enumerate(chunks, 1):
            canvas, pasted = _paste_chunk_canvas(
                paths_chunk, heights_chunk, ref_width, MAX_PDF_PAGE_HEIGHT,
                idx_offset, len(valid_paths),
            )
            idx_offset += len(paths_chunk)
            pasted_total += pasted

            temp_path = os.path.join(temp_dir, f"superpage_{ci:03d}.pdf")
            try:
                canvas.save(
                    temp_path,
                    "PDF",
                    resolution=IMAGE_RESOLUTION,
                    quality=_adaptive_jpeg_quality(*canvas.size),
                    optimize=True,
                    progressive=True,
                    subsampling=JPEG_SUBSAMPLING,
                )
                temp_pdf_paths.append(temp_path)
            except Exception as e:
                print(f"\n   [x] Gagal menyimpan halaman super {ci}: {e}")
            finally:
                canvas.close()

        print()

        if not temp_pdf_paths:
            print(f"   [x] Semua halaman super gagal disimpan untuk '{label}'.")
            return False

        success = _merge_pdfs(temp_pdf_paths, output_path)

    if success:
        print(f"   Saved: {os.path.relpath(output_path, os.path.dirname(os.path.dirname(output_path)))}")
        print(f"   Pages saved: {pasted_total}/{total_pages} (dalam {len(temp_pdf_paths)} halaman PDF)")

    return success


def convert_chapter_to_pdf(chapter_dir, output_path):
    chapter_name = os.path.basename(chapter_dir)
    image_paths = collect_images_from_folder(chapter_dir)

    if not image_paths:
        print(f"   [!] Tidak ada gambar di '{chapter_name}', dilewati.")
        return False

    ref_width = compute_reference_size(image_paths)

    return build_long_strip_pdf(image_paths, ref_width, output_path, chapter_name)


def prompt_chapter_range(chapters, completed_names):
    numbered = []
    for c in chapters:
        num = extract_chapter_number(os.path.basename(c))
        numbered.append((num, c))

    valid_nums = [n for n, _ in numbered if n is not None]
    if not valid_nums:
        print("   [!] Tidak bisa mendeteksi nomor chapter dari nama folder,")
        print("       semua chapter akan diproses.")
        return chapters

    not_done = [
        (num, path) for num, path in numbered
        if num is not None and get_chapter_label(os.path.basename(path)) not in completed_names
    ]

    default_start = min(n for n, _ in not_done) if not_done else min(valid_nums)
    default_end = max(valid_nums)

    def fmt(n):
        return f"{n:g}"

    raw_start = input(f"   Mulai chapter [{fmt(default_start)}]: ").strip()
    raw_end = input(f"   Sampai chapter [{fmt(default_end)}]: ").strip()

    try:
        start = float(raw_start) if raw_start else default_start
        end = float(raw_end) if raw_end else default_end
    except ValueError:
        print("   [!] Input tidak valid, memakai default.")
        start, end = default_start, default_end

    if start > end:
        start, end = end, start

    return [path for num, path in numbered if num is not None and start <= num <= end]


def print_pre_analysis_summary(source_dir, mode, numeric_score, merge_score):
    print("-" * 60)
    print("Analysis...")
    print("-" * 60)

    detected_label = "Per Chapter" if mode == "chapter" else "Multi Folder Merge"
    print(f"Detected Mode      : {detected_label}")
    print(f"Numeric Score      : {numeric_score:.1f}%")
    print(f"Merge Score        : {merge_score:.1f}%")

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

        print(f"Total Chapter      : {total}")
        print(f"Completed PDF      : {completed_count}")
        print(f"Remaining          : {remaining}")
        print(f"Output Folder      : {output_folder_name}")
        print(f"Image Count        : {image_count:,}")
    else:
        groups = group_folders_by_base_title(source_dir)
        completed_count = 0
        for base_title in groups:
            pdf_name = sanitize_filename(base_title) + ".pdf"
            if os.path.isfile(os.path.join(result_dir, pdf_name)):
                completed_count += 1

        print(f"Detected Series    : {len(groups)}")
        print(f"Completed PDF      : {completed_count}")
        print(f"Remaining          : {len(groups) - completed_count}")
        print(f"Output Folder      : {output_folder_name}")

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
        print("    Pastikan source dir langsung berisi folder-folder chapter")
        print("    (mis. Chapter_0000001, Chapter_0000002, ...).")
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
        print(f"   [!] Gagal mengirim notifikasi Telegram (start): {e}")

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
            print(f"   [x] Error tak terduga saat memproses '{chapter_name}': {e}")
            ok = False
            try:
                bot.error(chapter_num if chapter_num is not None else chapter_name, str(e), activity="Convert", comic=comic_title)
            except Exception as notif_err:
                print(f"   [!] Gagal mengirim notifikasi Telegram (error): {notif_err}")

        if ok:
            success_count += 1
        else:
            failed_count += 1
            try:
                bot.error(
                    chapter_num if chapter_num is not None else chapter_name,
                    "Gagal membuat PDF untuk chapter ini (lihat log terminal untuk detail)",
                    activity="Convert",
                    comic=comic_title,
                )
            except Exception as notif_err:
                print(f"   [!] Gagal mengirim notifikasi Telegram (error): {notif_err}")
        print()

    durasi = _format_duration(time.time() - run_start_time)
    total_processed = success_count + failed_count
    try:
        bot.finish(comic_title, total_processed, success_count, failed_count, durasi, activity="Convert")
    except Exception as e:
        print(f"   [!] Gagal mengirim notifikasi Telegram (finish): {e}")

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
        print(f"   [!] Tidak ada gambar sama sekali di grup '{base_title}', dilewati.")
        return False

    ref_width = compute_reference_size(all_image_paths)

    return build_long_strip_pdf(all_image_paths, ref_width, output_path, base_title)


def process_multi_folder_merge(source_dir):
    groups = group_folders_by_base_title(source_dir)
    if not groups:
        print("[!] Tidak ada folder ditemukan di dalam source dir.")
        return

    result_dir = get_result_dir(source_dir)

    print(f"   Total judul (base title) ditemukan: {len(groups)}\n")

    comic_title = os.path.basename(os.path.normpath(source_dir)) or source_dir

    run_start_time = time.time()
    try:
        bot.start(comic_title, 1, len(groups), activity="Convert")
    except Exception as e:
        print(f"   [!] Gagal mengirim notifikasi Telegram (start): {e}")

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
        print(f"Processing: {base_title}  ({len(folder_list)} folder: {folder_names})")

        try:
            ok = convert_group_to_pdf(base_title, folder_list, output_path)
        except Exception as e:
            print(f"   [x] Error tak terduga saat memproses '{base_title}': {e}")
            ok = False
            try:
                bot.error(base_title, str(e), activity="Convert", comic=comic_title)
            except Exception as notif_err:
                print(f"   [!] Gagal mengirim notifikasi Telegram (error): {notif_err}")

        if ok:
            success_count += 1
        else:
            failed_count += 1
            try:
                bot.error(
                    base_title,
                    "Gagal membuat PDF untuk grup ini (lihat log terminal untuk detail)",
                    activity="Convert",
                    comic=comic_title,
                )
            except Exception as notif_err:
                print(f"   [!] Gagal mengirim notifikasi Telegram (error): {notif_err}")
        print()

    durasi = _format_duration(time.time() - run_start_time)
    total_processed = success_count + failed_count
    try:
        bot.finish(comic_title, total_processed, success_count, failed_count, durasi, activity="Convert")
    except Exception as e:
        print(f"   [!] Gagal mengirim notifikasi Telegram (finish): {e}")

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
        print("    Coba lagi, atau ketik 'q' untuk keluar.\n")


def main():
    print("=" * 60)
    print("  Comic Folder -> PDF Converter (auto-detect mode, resumable)")
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