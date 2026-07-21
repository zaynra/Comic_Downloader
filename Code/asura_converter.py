import os
import re
from PIL import Image

def convert_chapters_to_pdf(comic_dir, base_result_dir=r"D:\zayn\comic_downloader\Result"):
    """
    Convert setiap folder chapter menjadi PDF tunggal.
    Hasil disimpan di: D:\zayn\comic_downloader\Result\[nama-folder-komik]\
    """
    # Ambil nama komik dari nama folder terakhir di path comic_dir
    comic_name = os.path.basename(os.path.normpath(comic_dir))
    comic_name = re.sub(r'[<>:"/\\|?*]', '_', comic_name).strip()  # aman dari karakter invalid
    
    # Path folder output PDF
    pdf_output_dir = os.path.join(base_result_dir, comic_name)
    os.makedirs(pdf_output_dir, exist_ok=True)
    
    print(f"Nama komik terdeteksi: {comic_name}")
    print(f"PDF akan disimpan di: {pdf_output_dir}\n")
    
    # Cari semua subfolder Chapter_
    chapter_folders = [
        f for f in os.listdir(comic_dir)
        if f.startswith('Chapter_') and os.path.isdir(os.path.join(comic_dir, f))
    ]
    
    if not chapter_folders:
        print("Tidak ditemukan folder Chapter_ di dalam direktori.")
        return
    
    # Urutkan berdasarkan nomor chapter
    def get_chapter_num(folder):
        match = re.search(r'Chapter_(\d+)', folder)
        return int(match.group(1)) if match else 999999
    
    chapter_folders.sort(key=get_chapter_num)
    
    print(f"Ditemukan {len(chapter_folders)} chapter untuk dikonversi.\n")
    
    for chapter_folder in chapter_folders:
        chapter_path = os.path.join(comic_dir, chapter_folder)
        images = []
        
        # Ambil file gambar
        files = [
            f for f in os.listdir(chapter_path)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        ]
        
        # Urutkan berdasarkan angka 3 digit di nama file
        def get_page_num(filename):
            match = re.search(r'(\d{3})', filename)
            return int(match.group(1)) if match else 9999
        
        files.sort(key=get_page_num)
        
        # Load gambar satu per satu
        for file in files:
            try:
                img_path = os.path.join(chapter_path, file)
                img = Image.open(img_path).convert('RGB')
                images.append(img)
            except Exception as e:
                print(f"  Skip {file} di {chapter_folder} karena error: {e}")
                continue
        
        if images:
            pdf_filename = f"{chapter_folder}.pdf"
            pdf_path = os.path.join(pdf_output_dir, pdf_filename)
            
            # Simpan sebagai PDF multi-page
            images[0].save(
                pdf_path,
                save_all=True,
                append_images=images[1:],
                quality=92,          # kualitas bagus tapi ukuran tidak terlalu besar
                optimize=True
            )
            print(f"Berhasil dibuat: {pdf_filename} ({len(images)} halaman)")
        else:
            print(f"Tidak ada gambar valid di {chapter_folder}")

if __name__ == "__main__":
    print("Konversi Chapter ke PDF - Versi Otomatis ke Result Folder")
    print("========================================================")
    
    comic_folder = input("Masukkan path folder komik (contoh: D:\\zayn\\Komik\\SSS-Class Suicide Hunter): ").strip()
    
    if not os.path.exists(comic_folder):
        print(f"Error: Folder '{comic_folder}' tidak ditemukan!")
    elif not os.path.isdir(comic_folder):
        print(f"Error: '{comic_folder}' bukan folder!")
    else:
        convert_chapters_to_pdf(comic_folder)
    
    print("\nSelesai.")
    input("Tekan Enter untuk keluar...")