import os
import re


# Prefix yang otomatis ditambahkan kalau nama file PDF TIDAK punya prefix
# sama sekali (murni angka, mis. "0001.pdf" -> "Chapter_0001.pdf").
DEFAULT_PREFIX = "Chapter_"


def format_number(num_str):
    """Ubah string angka (integer/desimal) menjadi padding 4 digit di bagian bulatnya.
    Contoh: '0000001' -> '0001', '0000041.5' -> '0041.5'
    """
    if '.' in num_str:
        int_part, _, dec_part = num_str.partition('.')
        return f"{int(int_part):04d}.{dec_part}"
    return f"{int(num_str):04d}"


def rename_pdfs(folder):
    if not os.path.isdir(folder):
        print(f"[ERROR] Folder tidak ditemukan: {folder}")
        return

    # Menangkap: <prefix apa saja><angka (boleh desimal)><.pdf>
    # Contoh cocok: "Chapter_0000001.pdf" -> prefix="Chapter_", number="0000001"
    # Contoh cocok: "0001.pdf" -> prefix="", number="0001"
    pattern = re.compile(r'^(?P<prefix>.*?)(?P<number>\d+(?:\.\d+)?)(?P<ext>\.pdf)$', re.IGNORECASE)

    files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
    files.sort()

    if not files:
        print("Tidak ada file PDF ditemukan di folder ini.")
        return

    renamed = 0
    skipped = 0

    for fname in files:
        match = pattern.match(fname)
        if not match:
            print(f"  Lewati (pola tidak cocok): {fname}")
            skipped += 1
            continue

        prefix = match.group('prefix')
        number = match.group('number')
        ext = match.group('ext')

        # Kalau file sama sekali tidak punya prefix (nama murni angka,
        # mis. "0001.pdf"), otomatis tambahkan DEFAULT_PREFIX.
        # File yang sudah punya prefix apa pun (mis. "Chapter_", "Ch",
        # "Vol1_") dibiarkan apa adanya -- hanya nomornya yang dirapikan.
        if prefix == '':
            prefix = DEFAULT_PREFIX

        new_name = f"{prefix}{format_number(number)}{ext}"

        old_path = os.path.join(folder, fname)
        new_path = os.path.join(folder, new_name)

        if old_path == new_path:
            skipped += 1
            continue

        if os.path.exists(new_path):
            print(f"  [SKIP] Nama tujuan sudah ada: {new_name}")
            skipped += 1
            continue

        # os.rename hanya mengubah metadata nama file (bukan copy isi file),
        # jadi tidak membebani RAM sama sekali, walaupun file PDF-nya besar.
        os.rename(old_path, new_path)
        print(f"  {fname}  ->  {new_name}")
        renamed += 1

    print("\nSelesai")
    print(f"Direname : {renamed}")
    print(f"Dilewati : {skipped}")


if __name__ == "__main__":
    folder = input("Masukkan lokasi folder PDF: ").strip().strip('"')
    rename_pdfs(folder)