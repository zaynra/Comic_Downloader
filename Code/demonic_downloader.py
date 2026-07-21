from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import requests
import os
import time
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from webdriver_manager.chrome import ChromeDriverManager
import sys


class DemonicDownloader:
    BASE_URL = "https://demonicscans.org"

    def __init__(self):
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/134.0.0.0 Safari/537.36'
            ),
            'Referer': self.BASE_URL,
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.max_workers = 4
        self.lock = Lock()
        self.stats = {'ok': 0, 'fail': 0, 'size': 0}

    def get_driver(self, enable_images: bool = True):
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--window-size=1280,900")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            img_pref = 1 if enable_images else 2
            options.add_experimental_option(
                "prefs",
                {"profile.managed_default_content_settings.images": img_pref}
            )

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver
        except Exception as e:
            print(f"[ERROR] Setup driver gagal: {e}")
            sys.exit(1)

    def clean_name(self, s: str) -> str:
        if not s:
            return "Unknown"
        return re.sub(r'[<>:"/\\|?*]', '', re.sub(r'\s+', ' ', str(s))).strip()[:80]

    def get_title(self, series_url: str) -> str:
        driver = None
        try:
            driver = self.get_driver(enable_images=False)
            driver.get(series_url)
            time.sleep(4)

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            candidates = [
                soup.select_one('h1'),
                soup.select_one('h2.series-title'),
                soup.select_one('.series-name'),
                soup.select_one('meta[property="og:title"]'),
            ]
            for tag in candidates:
                if tag:
                    txt = tag.get('content') or tag.get_text(strip=True)
                    if txt and len(txt) > 3 and "BETA" not in txt.upper():
                        return self.clean_name(txt)

            slug = series_url.rstrip('/').split('/')[-1]
            return self.clean_name(urllib.parse.unquote(slug))
        except Exception as e:
            print(f"[WARN] Gagal ambil title: {e}")
            return "Comic_Download"
        finally:
            if driver:
                driver.quit()

    def get_chapters(self, series_url: str):
        driver = None
        try:
            print("[INFO] Memuat halaman series, scroll untuk muat semua chapter...")
            driver = self.get_driver(enable_images=False)
            driver.get(series_url)
            time.sleep(4)

            last_h = driver.execute_script("return document.body.scrollHeight")
            for i in range(30):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)
                new_h = driver.execute_script("return document.body.scrollHeight")
                if new_h == last_h and i > 5:
                    break
                last_h = new_h
                print(f"  Scroll {i+1}/30", end="\r")

            print()
            time.sleep(2)

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            links = set()
            
            # Mencarinya sekarang berdasarkan URL format sebenarnya & class 'chplinks'
            for a in soup.find_all('a', href=True, class_='chplinks'):
                href = a['href']
                if 'chaptered.php' in href and '&chapter=' in href:
                    full = urllib.parse.urljoin(self.BASE_URL, href)
                    links.add(full)

            def chap_num(u):
                m = re.search(r'&chapter=([\d.]+)', u, re.I)
                return float(m.group(1)) if m else -1

            valid = sorted([u for u in links if chap_num(u) > 0], key=chap_num)
            print(f"[INFO] Ditemukan {len(valid)} chapter.")
            return valid

        except Exception as e:
            print(f"[ERROR] Gagal ambil daftar chapter: {e}")
            return []
        finally:
            if driver:
                driver.quit()

    def download_img(self, img_url: str, filepath: str) -> bool:
        try:
            r = self.session.get(img_url, timeout=15, stream=True)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
            size = os.path.getsize(filepath)
            if size < 2048:
                os.remove(filepath)
                with self.lock:
                    self.stats['fail'] += 1
                return False
            with self.lock:
                self.stats['ok'] += 1
                self.stats['size'] += size
            return True
        except Exception:
            with self.lock:
                self.stats['fail'] += 1
            return False

    def download_chapter(self, chap_url: str, base_folder: str) -> int:
        driver = None
        try:
            m = re.search(r'&chapter=([\d.]+)', chap_url, re.I)
            chap_num = m.group(1) if m else "unknown"
            
            # Format float rapi tanpa .0 jika integer
            folder_name = f"Chapter_{float(chap_num):04g}" if chap_num != "unknown" else "Chapter_Unknown"
            folder = os.path.join(base_folder, folder_name)
            os.makedirs(folder, exist_ok=True)

            print(f"\n[Chapter {chap_num}] Memuat halaman...")
            # Kita tidak perlu memuat gambarnya di browser untuk mengekstrak link-nya
            driver = self.get_driver(enable_images=False)
            driver.get(chap_url)
            time.sleep(3)

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            collected = []

            # Situs ini memiliki seluruh gambar di dalam tag <img> dengan class 'imgholder'
            for img in soup.find_all('img', class_='imgholder'):
                src = img.get('src')
                if src:
                    # Ganti prefix demoniclibs agar stabil jika divalidasi script JS asli situsnya
                    src = src.replace('demoniclibs.com', 'librarydm.com')
                    collected.append(src)

            if not collected:
                print(f"  Chapter {chap_num}: tidak ada gambar ditemukan.")
                return 0

            print(f"  Chapter {chap_num}: {len(collected)} halaman ditemukan, mulai download...")

            self.stats = {'ok': 0, 'fail': 0, 'size': 0}

            tasks = []
            for page_idx, img_url in enumerate(collected, 1):
                ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1] or '.jpg'
                filepath = os.path.join(folder, f"{page_idx:03d}{ext}")
                tasks.append((img_url, filepath))

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self.download_img, u, p): i for i, (u, p) in enumerate(tasks, 1)}
                done = 0
                for fut in as_completed(futures):
                    done += 1
                    if done % 5 == 0 or done == len(tasks):
                        print(f"  Progress: {done}/{len(tasks)} "
                              f"({self.stats['ok']} berhasil, {self.stats['fail']} gagal)", end="\r")

            mb = self.stats['size'] / 1_048_576
            print(f"\n  Chapter {chap_num} selesai: "
                  f"{self.stats['ok']}/{len(collected)} halaman ({mb:.1f} MB)")
            return self.stats['ok']

        except Exception as e:
            print(f"\n[ERROR] Download chapter gagal: {e}")
            return 0
        finally:
            if driver:
                driver.quit()

    def run(self, series_url: str, start_ch: float = 1, end_ch: float = 9999):
        title = self.get_title(series_url)
        base_folder = os.path.join("Komik", title)
        os.makedirs(base_folder, exist_ok=True)
        print(f"[INFO] Judul   : {title}")
        print(f"[INFO] Folder  : {base_folder}\n")

        chapters = self.get_chapters(series_url)
        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan. Cek URL series atau koneksi internet.")
            return

        to_download = []
        for url in chapters:
            m = re.search(r'&chapter=([\d.]+)', url, re.I)
            if m:
                num = float(m.group(1))
                if start_ch <= num <= end_ch:
                    to_download.append((num, url))

        to_download.sort(key=lambda x: x[0])

        if not to_download:
            print(f"[WARN] Tidak ada chapter dalam range {start_ch}–{end_ch}.")
            return

        print(f"[INFO] Akan download {len(to_download)} chapter (range {start_ch}–{end_ch})\n")

        total_pages = 0
        for idx, (num, url) in enumerate(to_download, 1):
            print(f"[{idx}/{len(to_download)}] Chapter {num:.1f}  →  {url}")
            pages = self.download_chapter(url, base_folder)
            total_pages += pages
            time.sleep(2.5)

        print(f"\n{'='*50}")
        print(f"SELESAI")
        print(f"Total halaman berhasil : {total_pages}")
        print(f"Lokasi file            : {os.path.abspath(base_folder)}")
        print(f"{'='*50}")


if __name__ == "__main__":
    print("Demonic Scans Downloader")
    print("Mendukung: https://demonicscans.org")
    print("-" * 50)

    url = input("Masukkan URL series (contoh: https://demonicscans.org/manga/Mairimashita%21-Iruma-kun): ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    start_input = input("Chapter mulai (default 1): ").strip()
    end_input   = input("Chapter akhir (default semua): ").strip()

    start = float(start_input) if start_input else 1
    end   = float(end_input)   if end_input   else 9999

    downloader = DemonicDownloader()
    downloader.run(url, start, end)