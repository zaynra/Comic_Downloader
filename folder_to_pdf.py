import os
import re
import shutil
import tempfile
from collections import defaultdict

from PIL import Image
from pypdf import PdfWriter

# Nonaktifkan limit "decompression bomb" bawaan Pillow. Karena sekarang
# satu chapter digabung jadi SATU kanvas raksasa (lebar x total tinggi
# semua gambar), total pixel-nya bisa gampang melewati default limit
# Pillow (~89 juta pixel) walau tiap gambar aslinya wajar. Ini murni
# penyesuaian teknis supaya proses gabung tidak dihentikan paksa oleh
# Pillow, TIDAK mengubah perilaku/flow program sama sekali.
Image.MAX_IMAGE_PIXELS = None

# ------------------------------------------------------------------------
# KONFIGURASI
# ------------------------------------------------------------------------

# Default source folder — dipakai kalau user tidak mengisi apa-apa saat
# ditanya di terminal (lihat prompt_source_dir()).
DEFAULT_SOURCE_DIR = r"D:\zayn\comic_downloader\source"

# Kandidat nama folder output, dicek dalam urutan prioritas ini. Kalau
# salah satu SUDAH ADA sebagai folder di source_dir, folder itu yang
# dipakai (menjaga kompatibilitas dgn struktur folder user). Kalau tidak
# ada satupun yang sudah ada, baru dibuat "Result".
OUTPUT_FOLDER_CANDIDATES = ["Result", "PDF", "Output"]
RESULT_FOLDER_NAME = OUTPUT_FOLDER_CANDIDATES[0]

IMAGE_RESOLUTION = 300.0
IMAGE_QUALITY = 95

# Prefix nama file PDF untuk mode 1 (per-chapter). Dipakai saat MENULIS
# PDF baru. Resume/pengecekan "sudah selesai" TIDAK bergantung pada
# prefix ini -- get_chapter_label() mengekstrak angka dari nama file apa
# adanya, jadi PDF lama tanpa prefix ("0001.pdf") maupun PDF baru dengan
# prefix ("Chapter_0001.pdf") sama-sama dikenali sebagai chapter yang sama.
CHAPTER_PDF_PREFIX = "Chapter_"


# ------------------------------------------------------------------------
# UTIL: NATURAL SORT
# ------------------------------------------------------------------------

def natural_sort_key(name):
    """
    True natural sort: split string into text and integer chunks,
    so '2' < '10' < '20' instead of lexicographic '10' < '2' < '20'.
    """
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


# ------------------------------------------------------------------------
# UTIL: CHAPTER LABEL (dukungan folder 8-digit & 4-digit, output selalu 4-digit)
# ------------------------------------------------------------------------

def extract_chapter_number(name):
    """
    Ekstrak nomor chapter dari sebuah nama (folder atau nama file PDF),
    berapa pun jumlah digitnya -- '00000071', '0071', 'Chapter_0000001',
    dst semuanya cukup diambil angkanya. Mendukung angka desimal
    (mis. '0004.5') kalau suatu saat ada. Return None kalau nama sama
    sekali tidak mengandung angka.
    """
    m = re.search(r'(\d+(?:\.\d+)?)', name)
    if not m:
        return None
    return float(m.group(1))


def format_chapter_label(num):
    """Selalu hasilkan label 4-digit, apa pun jumlah digit sumbernya."""
    if float(num).is_integer():
        return f"{int(num):04d}"
    integer_part, _, decimal_part = f"{num:g}".partition('.')
    return f"{int(integer_part):04d}.{decimal_part}"


def get_chapter_label(name):
    """
    Label kanonis yang dipakai untuk pencocokan resume (dan sebagai basis
    nama PDF output di mode 1), supaya folder '00000071' dan '0071'
    (atau PDF lama/baru bernama '00000071.pdf', '0071.pdf',
    'Chapter_0071.pdf') dikenali sebagai chapter yang sama dan selalu
    menghasilkan label 4-digit ('0071').

    Kalau nama sama sekali tidak mengandung angka (folder dengan nama
    aneh/non-numerik), fallback ke nama asli yang sudah disanitize supaya
    tetap kompatibel dengan folder lama yang tidak mengikuti pola angka.
    """
    num = extract_chapter_number(name)
    if num is not None:
        return format_chapter_label(num)
    return sanitize_filename(name)


def format_chapter_pdf_filename(chapter_label):
    """
    Nama file PDF final untuk mode 1 (per-chapter), mis. 'Chapter_0071.pdf'.
    Terpisah dari get_chapter_label() supaya label kanonis (dipakai untuk
    resume matching) dan nama file aktual (dipakai untuk penulisan) tidak
    tercampur -- hanya fungsi ini yang menambahkan prefix CHAPTER_PDF_PREFIX.
    """
    return f"{CHAPTER_PDF_PREFIX}{chapter_label}.pdf"


# ------------------------------------------------------------------------
# UTIL: IMAGE HANDLING
# ------------------------------------------------------------------------

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
    """
    Scale image width to ref_width (keep aspect ratio). Tinggi kanvas
    mengikuti tinggi asli gambar apa adanya -- TIDAK ada padding putih
    ke tinggi seragam, supaya halaman pendek (cover/credit page) tidak
    diberi gap putih raksasa dan hasil PDF menyambung mulus seperti
    tampilan aslinya di website.
    """
    orig_w, orig_h = image.size
    scale = ref_width / orig_w
    new_w = ref_width
    new_h = round(orig_h * scale)

    return image.resize((new_w, new_h), Image.LANCZOS)


def compute_reference_size(image_paths):
    """
    Read only image *dimensions* (Image.open is lazy, doesn't decode pixel
    data), so this stays cheap even for hundreds of pages.

    Cuma butuh ref_width (biar semua halaman seragam lebarnya saat
    digabung) -- ref_height sudah tidak dipakai lagi karena tinggi tiap
    halaman kini mengikuti aslinya masing-masing (lihat normalize_to_reference).
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

    return max(widths)


# ------------------------------------------------------------------------
# AUTO-DETECT MODE (Per Chapter vs Multi Folder Merge)
# ------------------------------------------------------------------------
#
# Sebelumnya user diminta memilih mode secara manual lewat prompt_mode().
# Sekarang mode ditentukan otomatis dari struktur folder di dalam
# source_dir, memakai sistem SCORING (bukan cuma menebak dari satu
# folder) supaya lebih aman terhadap folder campuran (mis. ada
# "Cover"/"Extras" di antara folder chapter bernomor).
#
# Skema klasifikasi tiap subfolder (exclude folder output):
#   - "numeric" -> nama folder murni angka / angka dgn prefix umum
#     seperti "Chapter_", "Chapter ", "Ch", "Episode" (mis. "0001",
#     "Chapter_0000071", "Ch 12"). Ini ciri khas mode Per Chapter.
#   - "merge"   -> nama folder = judul + nomor urut, judulnya BUKAN
#     sekadar kata generik "chapter/ch/episode" (mis. "Titan 1",
#     "Titan_002"). Ini ciri khas mode Multi Folder Merge.
#   - "none"    -> tidak ada angka di ujung nama (mis. "Cover", "Extras"),
#     diabaikan dari perhitungan skor (bukan penentu mode).
#
# Numeric Score / Merge Score dihitung sebagai persentase dari folder
# yang berhasil diklasifikasi ("numeric" + "merge"), lalu mode yang
# skornya lebih tinggi yang dipilih. Kalau tidak ada satupun folder yang
# bisa diklasifikasi (semua "none"), default ke mode Per Chapter (lebih
# aman -- tiap folder tetap diproses sebagai satu chapter apa adanya).

CHAPTER_PREFIX_WORDS = ("chapter", "chapitre", "episode", "chap", "chp", "ep", "ch")

# Nama folder yang MURNI angka (boleh diapit spasi/underscore/strip), mis.
# "0001", "00000071", " 12 " -> classify_folder_name() = "numeric".
_NUMERIC_ONLY_PATTERN = re.compile(r'^[\s_\-]*\d+(?:\.\d+)?[\s_\-]*$')


def classify_folder_name(name):
    """
    Klasifikasikan satu nama folder -> 'numeric' / 'merge' / 'none'.

    - "numeric": nama folder murni angka ("0001"), atau angka dengan
      prefix generik yang jelas menandakan chapter/episode ("Chapter_0001",
      "Ch 12", "Episode 3"). Ciri khas mode Per Chapter.
    - "merge": nama folder = judul (bukan kata generik chapter/episode) +
      nomor urut di akhir ("Titan 1", "Titan_002"). Ciri khas mode Multi
      Folder Merge.
    - "none": tidak ada angka di ujung nama (mis. "Cover", "Extras").
    """
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
    """
    Analisis seluruh subfolder langsung di dalam source_dir (exclude
    folder output) dan kembalikan tuple:
        (mode, numeric_score, merge_score, classified_count, total_folders)
    mode adalah "chapter" atau "merge".
    """
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
        # Tidak ada folder yang bisa diklasifikasi -- default aman: Per
        # Chapter (setiap folder diperlakukan sebagai satu chapter).
        return "chapter", 0.0, 0.0, classified_count, total_folders

    numeric_score = round(100 * numeric_count / classified_count, 1)
    merge_score = round(100 * merge_count / classified_count, 1)

    mode = "merge" if merge_count > numeric_count else "chapter"
    return mode, numeric_score, merge_score, classified_count, total_folders


# ------------------------------------------------------------------------
# SCAN: CHAPTERS
# ------------------------------------------------------------------------
#
# Struktur yang didukung (satu folder komik per run):
#
#   <source_dir>/                <- ini yang diinput user di terminal
#   |-- Chapter_0000001/         <- langsung berisi gambar (1.jpg, 2.jpg, ...)
#   |-- Chapter_0000002/
#   |-- Chapter_0000003/
#   `-- Result/                  <- dibuat otomatis (atau "PDF"/"Output" kalau sudah ada)
#       |-- Chapter_0000001.pdf
#       `-- Chapter_0000002.pdf
#
# Tidak ada level "Nama Komik" terpisah -- source_dir yang diinput SUDAH
# berarti satu komik, dan setiap subfolder langsung di dalamnya adalah
# satu chapter yang isinya gambar.
#
# Nama folder chapter boleh 8-digit ('00000001') maupun 4-digit ('0001')
# -- keduanya valid dan dikenali sebagai chapter yang sama lewat
# get_chapter_label() di atas (dipakai saat penamaan PDF & resume).

def scan_chapter_folders(source_dir):
    """Chapter subfolders langsung di dalam source_dir, exclude folder output."""
    chapters = [
        entry.path for entry in os.scandir(source_dir)
        if entry.is_dir() and entry.name not in OUTPUT_FOLDER_CANDIDATES
    ]
    chapters.sort(key=lambda p: natural_sort_key(os.path.basename(p)))
    return chapters


def get_result_dir(source_dir):
    """
    Folder output fleksibel: cek OUTPUT_FOLDER_CANDIDATES ("Result",
    "PDF", "Output") dalam urutan prioritas itu. Kalau salah satu SUDAH
    ADA sebagai folder, folder itu yang dipakai (menjaga kompatibilitas
    dgn struktur folder user yang sudah ada). Kalau tidak ada satupun
    yang sudah ada, baru dibuat "Result".
    """
    for candidate in OUTPUT_FOLDER_CANDIDATES:
        candidate_path = os.path.join(source_dir, candidate)
        if os.path.isdir(candidate_path):
            return candidate_path

    result_dir = os.path.join(source_dir, RESULT_FOLDER_NAME)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir


def get_completed_chapter_names(result_dir):
    """
    Label chapter (sudah dinormalisasi ke 4-digit lewat get_chapter_label)
    yang sudah punya PDF di Result. Normalisasi ini juga berlaku untuk
    PDF lama yang mungkin masih bernama 8-digit, PDF lama tanpa prefix
    ('0071.pdf'), maupun PDF baru dengan prefix ('Chapter_0071.pdf') --
    get_chapter_label() cuma mengekstrak angkanya, jadi prefix apapun
    (atau tidak ada prefix sama sekali) tetap dikenali sebagai chapter
    yang sama saat resume.
    """
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


# ------------------------------------------------------------------------
# CORE: BUILD LONG-STRIP PDF (AS FEW PAGES AS POSSIBLE, LOW-RAM, TWO-PASS)
# ------------------------------------------------------------------------
#
# Sebelumnya tiap gambar dijadikan 1 halaman PDF terpisah lalu semua
# halaman itu di-merge dengan pypdf -> hasilnya PDF multi-page, dan
# hampir semua PDF reader menampilkan jarak/background di antara
# halaman saat discroll.
#
# Sekarang seluruh gambar (satu chapter, atau satu grup di mode 2)
# digabung dulu jadi kanvas Pillow panjang (lebar = ref_width, tinggi =
# total tinggi semua gambar setelah discale), baru kanvas itu disimpan
# sebagai halaman PDF. Idealnya cuma SATU halaman per chapter/grup.
#
# BATASAN TEKNIS: encoder JPEG-di-dalam-PDF milik Pillow punya batas
# keras "Maximum supported image dimension is 65500 pixels" per sisi
# kanvas. Chapter dengan sangat banyak gambar tinggi bisa membuat total
# tinggi kanvas melewati batas itu. Kalau dipaksakan tetap 1 kanvas,
# Image.save(..., "PDF", ...) akan gagal seperti yang terjadi
# sebelumnya. Supaya tetap valid, kalau total tinggi chapter melewati
# batas ini, kanvas dipecah jadi beberapa "halaman super" -- tiap
# halaman super tetap diisi SEBANYAK MUNGKIN gambar (bukan 1 gambar =
# 1 halaman seperti versi lama), baru pindah ke halaman super
# berikutnya begitu batas tinggi hampir tercapai. Hasilnya PDF tetap
# jauh lebih sedikit halaman/jarak dibanding sebelumnya (mis. chapter
# 72 gambar yang dulu jadi 72 halaman, sekarang biasanya cukup 1-2
# halaman saja), dan pemecahan hanya terjadi kalau benar-benar
# diharuskan oleh batas teknis Pillow, bukan lagi per-gambar.
#
# Supaya RAM tetap rendah walau kanvas akhirnya besar, prosesnya dua
# tahap:
#   1) PASS 1 (ringan): buka tiap gambar cuma untuk baca ukurannya
#      (Image.open itu lazy, belum decode pixel) -> hitung tinggi hasil
#      scale masing-masing -> jumlahkan jadi total_height.
#   2) Kelompokkan gambar jadi satu atau beberapa "halaman super"
#      berdasarkan batas tinggi tersebut (tanpa memotong isi gambar,
#      cuma menentukan di gambar mana halaman super berikutnya mulai).
#   3) Untuk tiap halaman super: buat kanvas kosong seukuran itu, lalu
#      PASS 2 -- buka gambar SATU PER SATU, convert_to_rgb() +
#      normalize_to_reference() seperti sebelumnya, tempel ke kanvas,
#      tutup gambar itu sebelum lanjut ke gambar berikutnya -- tidak
#      pernah menahan lebih dari satu gambar sumber di RAM sekaligus.
#   4) Kalau cuma ada satu halaman super, langsung disimpan sebagai
#      output_path (PDF satu halaman, sama seperti sebelumnya). Kalau
#      lebih dari satu, tiap halaman super disimpan sebagai PDF
#      sementara lalu digabung (pypdf) jadi satu file output_path yang
#      berisi beberapa halaman super tsb.

# Margin aman di bawah batas keras Pillow (65500px) untuk sisi kanvas
# saat disimpan sebagai PDF/JPEG.
MAX_PDF_PAGE_HEIGHT = 65000


def _compute_scaled_heights(image_paths, ref_width):
    """
    PASS 1: baca ukuran tiap gambar (tanpa decode pixel) dan hitung tinggi
    hasil scale ke ref_width. Gambar yang gagal dibaca di-skip di sini,
    supaya PASS 2 tidak perlu menghitung ulang & kanvas bisa dibuat pas
    ukurannya dari awal (tidak perlu resize kanvas belakangan).

    Return: (valid_paths, heights, total_height)
    """
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
    """
    Kelompokkan gambar (urut apa adanya, tidak diacak) jadi beberapa
    "halaman super" supaya total tinggi tiap kelompok tidak melewati
    max_height. Mengisi tiap kelompok SEPENUH mungkin sebelum pindah ke
    kelompok berikutnya, jadi jumlah kelompok seminimal mungkin.

    Kasus langka: satu gambar SENDIRIAN sudah lebih tinggi dari
    max_height (setelah discale ke ref_width). Gambar itu tetap
    dikelompokkan sendirian (tidak dipotong) -- penyesuaian lebih
    lanjut (downscale khusus halaman itu) ditangani di _paste_chunk_canvas.
    """
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
    """
    Tempel satu kelompok gambar (satu "halaman super") ke satu kanvas
    Pillow, gambar per gambar, low-RAM (sama seperti sebelumnya).

    Kasus langka: kalau kelompok ini cuma berisi satu gambar yang
    sendirian sudah lebih tinggi dari max_height, kanvas (dan gambar
    itu) diskalakan turun proporsional supaya muat batas PDF -- ini
    satu-satunya situasi lebar bisa sedikit lebih kecil dari ref_width,
    dan hanya terjadi kalau gambar aslinya memang sangat panjang.
    """
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
            # Gambar ini sudah lolos PASS 1 (ukurannya terbaca) tapi gagal
            # dibuka/diproses di PASS 2 (jarang terjadi, mis. file korup
            # secara parsial). Ruang yang sudah dialokasikan untuknya di
            # kanvas dibiarkan putih polos (tidak fatal, tidak menambah
            # halaman baru, cuma strip putih sepanjang tinggi gambar itu).
            y += h
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass

    return canvas, pasted


def _merge_pdfs(temp_pdf_paths, output_path):
    """Gabungkan beberapa PDF satu-halaman jadi satu file multi-halaman."""
    writer = PdfWriter()
    try:
        for temp_path in temp_pdf_paths:
            writer.append(temp_path)

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
    """
    Gabungkan semua gambar di image_paths menjadi kanvas vertikal
    panjang sesedikit mungkin (idealnya cuma satu), lalu simpan sebagai
    PDF di output_path.

    Dipakai bersama oleh convert_chapter_to_pdf() (mode 1) dan
    convert_group_to_pdf() (mode 2) -- logikanya identik, cuma sumber
    image_paths-nya beda (satu folder vs gabungan beberapa folder).

    Tidak menambah margin/padding/spasi apa pun antar gambar. Lebar
    kanvas = ref_width (dari compute_reference_size(), tidak berubah).
    Tinggi tiap gambar tetap mengikuti proporsi aslinya (lewat
    normalize_to_reference(), tidak berubah). Pemecahan jadi lebih dari
    satu halaman HANYA terjadi kalau total tinggi chapter melewati
    batas teknis PDF/Pillow (lihat MAX_PDF_PAGE_HEIGHT di atas).
    """
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
        # Kasus normal: semua muat di satu halaman panjang.
        canvas, pasted = _paste_chunk_canvas(
            valid_paths, heights, ref_width, MAX_PDF_PAGE_HEIGHT, 0, len(valid_paths)
        )
        print()  # newline after progress overwrite

        success = True
        try:
            canvas.save(
                output_path,
                "PDF",
                resolution=IMAGE_RESOLUTION,
                quality=IMAGE_QUALITY,
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

    # Kasus jarang: total tinggi melewati batas teknis PDF -- pecah jadi
    # beberapa halaman super, isi sepenuh mungkin tiap halaman.
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
                canvas.save(temp_path, "PDF", resolution=IMAGE_RESOLUTION, quality=IMAGE_QUALITY)
                temp_pdf_paths.append(temp_path)
            except Exception as e:
                print(f"\n   [x] Gagal menyimpan halaman super {ci}: {e}")
            finally:
                canvas.close()

        print()  # newline after progress overwrite

        if not temp_pdf_paths:
            print(f"   [x] Semua halaman super gagal disimpan untuk '{label}'.")
            return False

        success = _merge_pdfs(temp_pdf_paths, output_path)
        # temp_dir (dan semua PDF halaman super di dalamnya) otomatis
        # dihapus di sini.

    if success:
        print(f"   Saved: {os.path.relpath(output_path, os.path.dirname(os.path.dirname(output_path)))}")
        print(f"   Pages saved: {pasted_total}/{total_pages} (dalam {len(temp_pdf_paths)} halaman PDF)")

    return success


def convert_chapter_to_pdf(chapter_dir, output_path):
    """
    Mode 1: satu chapter folder -> satu PDF (satu halaman panjang).
    Interface/return value sama seperti sebelumnya, isinya sekarang
    delegasi ke build_long_strip_pdf().
    """
    chapter_name = os.path.basename(chapter_dir)
    image_paths = collect_images_from_folder(chapter_dir)

    if not image_paths:
        print(f"   [!] Tidak ada gambar di '{chapter_name}', dilewati.")
        return False

    ref_width = compute_reference_size(image_paths)

    return build_long_strip_pdf(image_paths, ref_width, output_path, chapter_name)


# ------------------------------------------------------------------------
# RANGE SELECTION / RESUME LOGIC
# ------------------------------------------------------------------------

def prompt_chapter_range(chapters, completed_names):
    """
    Show total / done / not-done counts, then ask for start/end chapter
    berdasarkan NOMOR CHAPTER ASLI (diambil dari nama folder lewat
    extract_chapter_number), BUKAN posisi index di dalam list.

    Ini penting: kalau daftar folder punya celah, duplikat gaya penamaan
    (8-digit & 4-digit sekaligus), atau urutan yang tidak rapi, posisi
    ke-N di list belum tentu = chapter nomor N. Memakai nomor chapter
    asli memastikan input "80" SELALU merujuk ke folder chapter 80,
    apa pun posisinya di list.

    Empty input defaults to:
        start = nomor chapter belum-selesai yang paling kecil
        end   = nomor chapter terbesar yang ditemukan
    """
    numbered = []
    for c in chapters:
        num = extract_chapter_number(os.path.basename(c))
        numbered.append((num, c))

    valid_nums = [n for n, _ in numbered if n is not None]
    if not valid_nums:
        # Tidak ada satupun folder yang mengandung angka chapter --
        # tidak bisa difilter berdasarkan nomor, proses semua saja.
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

    # Filter berdasarkan nomor chapter asli, bukan posisi di list.
    return [path for num, path in numbered if num is not None and start <= num <= end]


# ------------------------------------------------------------------------
# RINGKASAN ANALISIS SEBELUM PROSES DIMULAI
# ------------------------------------------------------------------------

def print_pre_analysis_summary(source_dir, mode, numeric_score, merge_score):
    """
    Tampilkan ringkasan hasil analisis SEBELUM proses/prompt interaktif
    dimulai, supaya user tahu persis apa yang akan diproses.
    """
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


# ------------------------------------------------------------------------
# PROSES SEMUA CHAPTER TERPILIH
# ------------------------------------------------------------------------

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

    print()
    for chapter_dir in selected_chapters:
        chapter_name = os.path.basename(chapter_dir)
        chapter_label = get_chapter_label(chapter_name)

        if chapter_label in completed_names:
            print(f"[skip] {chapter_name} (PDF sudah ada)")
            continue

        output_path = os.path.join(result_dir, format_chapter_pdf_filename(chapter_label))

        print(f"Processing: {chapter_name}")
        convert_chapter_to_pdf(chapter_dir, output_path)
        print()


# ------------------------------------------------------------------------
# MODE 2: MULTI-FOLDER MERGE (gabung banyak folder chapter dgn base title
# sama jadi SATU PDF, mis. 'Titan 1'/'Titan 2'/'Titan 3' -> 'Titan.pdf')
#
# Mode ini terpisah total dari mode per-chapter di atas -- tidak ada satu
# pun fungsi/variabel milik mode lama yang diubah. Fungsi inti yang sudah
# ada (natural_sort_key, sanitize_filename, collect_images_from_folder,
# compute_reference_size, get_result_dir) dipakai ulang apa adanya, dan
# pembuatan PDF-nya kini juga lewat build_long_strip_pdf() yang sama
# dipakai mode 1.
# ------------------------------------------------------------------------

# Pisahkan "Titan 1" -> ('Titan', 1). Separator boleh spasi/underscore/
# strip, atau tanpa separator sama sekali ('Titan1'). Angka WAJIB ada di
# paling akhir nama folder supaya dianggap nomor urut chapter, bukan
# bagian dari judul.
BASE_TITLE_PATTERN = re.compile(r'^(.*?)[\s_\-]*(\d+)$')


def extract_base_title(folder_name):
    """
    Pisahkan nama folder menjadi (base_title, nomor_urut).
    'Titan 1' -> ('Titan', 1), 'Titan 10' -> ('Titan', 10).
    Kalau nama folder tidak diakhiri angka (mis. 'Extras'), base_title =
    nama folder itu sendiri dan nomor_urut = None -- folder seperti ini
    otomatis jadi grupnya sendiri (satu folder = satu PDF bernama sama
    dengan folder itu).
    """
    m = BASE_TITLE_PATTERN.match(folder_name.strip())
    if not m or not m.group(1).strip():
        return folder_name.strip(), None
    return m.group(1).strip(), int(m.group(2))


def group_folders_by_base_title(source_dir):
    """
    Kelompokkan subfolder langsung di dalam source_dir (exclude folder
    output) berdasarkan base title. Folder di dalam tiap grup diurutkan
    pakai natural_sort_key pada nama folder ASLI (bukan cuma angka hasil
    parsing) supaya 'Titan 1' < 'Titan 2' < ... < 'Titan 10' < 'Titan 11'
    -- konsisten dengan cara mode per-chapter mengurutkan. natural_sort_key
    mengonversi setiap potongan angka jadi int(), jadi padding berapa pun
    ('00000001' vs '0002') tetap terurut benar berdasarkan nilai numeriknya,
    bukan perbandingan string.

    Return: dict {base_title: [folder_path, ...]} yang setiap grupnya
    sudah terurut, dan grup-grup itu sendiri diurutkan alfabetis
    (case-insensitive) supaya output stabil dan mudah diprediksi.
    """
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
    """
    Sama seperti convert_chapter_to_pdf, tapi sumber gambarnya berasal
    dari BEBERAPA folder (satu base title) yang digabung jadi satu PDF
    satu-halaman-panjang, urut sesuai folder_list (harus sudah
    natural-sorted oleh group_folders_by_base_title) -- gambar di dalam
    tiap folder juga diurutkan natural sort lewat collect_images_from_folder
    yang sudah ada, sehingga halaman tidak pernah tercampur antar chapter.
    """
    all_image_paths = []
    for folder in folder_list:
        all_image_paths.extend(collect_images_from_folder(folder))

    if not all_image_paths:
        print(f"   [!] Tidak ada gambar sama sekali di grup '{base_title}', dilewati.")
        return False

    ref_width = compute_reference_size(all_image_paths)

    return build_long_strip_pdf(all_image_paths, ref_width, output_path, base_title)


def process_multi_folder_merge(source_dir):
    """
    Entry point mode 2: scan -> group by base title -> resume check
    ('Titan.pdf' sudah ada? skip, jangan overwrite) -> convert per grup.
    """
    groups = group_folders_by_base_title(source_dir)
    if not groups:
        print("[!] Tidak ada folder ditemukan di dalam source dir.")
        return

    result_dir = get_result_dir(source_dir)

    print(f"   Total judul (base title) ditemukan: {len(groups)}\n")

    for base_title, folder_list in groups.items():
        pdf_name = sanitize_filename(base_title) + ".pdf"
        output_path = os.path.join(result_dir, pdf_name)

        if os.path.isfile(output_path):
            print(f"Skip {base_title} (PDF sudah ada)")
            continue

        folder_names = ", ".join(os.path.basename(f) for f in folder_list)
        print(f"Processing: {base_title}  ({len(folder_list)} folder: {folder_names})")
        convert_group_to_pdf(base_title, folder_list, output_path)
        print()


# ------------------------------------------------------------------------
# INPUT SOURCE DIRECTORY
# ------------------------------------------------------------------------

def prompt_source_dir():
    """
    Tanyakan lokasi folder source ke user lewat terminal.
    - Enter kosong -> pakai DEFAULT_SOURCE_DIR.
    - Path tidak valid -> tanya ulang (atau ketik 'q' untuk keluar).
    Path boleh diketik dengan atau tanpa tanda kutip di awal/akhir.
    """
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


# ------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Comic Folder -> PDF Converter (auto-detect mode, resumable)")
    print("=" * 60)

    source_dir = prompt_source_dir()
    if source_dir is None:
        print("Dibatalkan oleh user.")
        return

    print(f"\nSource: {source_dir}\n")

    # Mode tidak lagi dipilih manual -- dideteksi otomatis dari struktur
    # folder memakai sistem scoring (lihat detect_processing_mode()).
    mode, numeric_score, merge_score, classified_count, total_folders = detect_processing_mode(source_dir)

    print_pre_analysis_summary(source_dir, mode, numeric_score, merge_score)

    if mode == "merge":
        process_multi_folder_merge(source_dir)
    else:
        process_chapters(source_dir)

    print("Semua proses selesai!")


if __name__ == "__main__":
    main()