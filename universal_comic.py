from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import requests
import os
os.environ.setdefault('WDM_LOG', '0')
os.environ.setdefault('WDM_LOG_LEVEL', '0')
os.environ.setdefault('WDM_PRINT_FIRST_LINE', 'False')
import time
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from webdriver_manager.chrome import ChromeDriverManager


# ============================================================
# UTILITAS UMUM (driver, nama file, download gambar, threading)
# ============================================================

class ComicDownloaderCore:
    def __init__(self, max_workers=6):
        self.headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/134.0.0.0 Safari/537.36'),
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.max_workers = max_workers
        self.lock = Lock()
        self.stats = {'ok': 0, 'fail': 0, 'size': 0}

    def get_driver(self, enable_images=True):
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

            prefs = {"profile.managed_default_content_settings.images": 1 if enable_images else 2}
            options.add_experimental_option("prefs", prefs)

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver
        except Exception as e:
            print(f"[ERROR] Setup driver gagal: {e}")
            sys.exit(1)

    def clean_name(self, s):
        if not s:
            return "Unknown"
        return re.sub(r'[<>:"/\\|?*]', '', re.sub(r'\s+', ' ', str(s))).strip()[:80]

    def download_img(self, img_url, filepath, min_size=2048):
        try:
            r = self.session.get(img_url, timeout=15, stream=True)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
            size = os.path.getsize(filepath)
            if size < min_size:
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

    def download_images(self, tasks):
        """tasks: list of (url, filepath). Menggunakan thread pool + progress print."""
        self.stats = {'ok': 0, 'fail': 0, 'size': 0}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self.download_img, u, p) for u, p in tasks]
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if completed % 5 == 0 or completed == len(tasks):
                    print(f"  Progress: {completed}/{len(tasks)} "
                          f"({self.stats['ok']} berhasil, {self.stats['fail']} gagal)", end="\r")
        print()
        return self.stats


# ============================================================
# SITE ADAPTERS
# Setiap adapter wajib punya: get_title, get_chapters, get_chapter_images
# get_chapters harus return list URL chapter (belum difilter angka).
# get_chapter_num harus bisa ekstrak nomor chapter dari sebuah URL chapter.
# ============================================================

class BaseSiteAdapter:
    name = "generic"

    def __init__(self, core: ComicDownloaderCore):
        self.core = core

    def get_title(self, driver, series_url):
        raise NotImplementedError

    def get_chapters(self, driver, series_url):
        raise NotImplementedError

    def get_chapter_num(self, chap_url):
        raise NotImplementedError

    def get_chapter_images(self, driver, chap_url):
        raise NotImplementedError


class GenericSiteAdapter(BaseSiteAdapter):
    """
    Adapter generik (basis dari AsuraDownloader), dipakai untuk situs
    apapun yang tidak punya adapter khusus. Mengandalkan pola umum:
    - Link chapter: href mengandung kata chapter/ch/c/ep diikuti angka.
    - Halaman chapter: gambar ada di container reader umum
      (div#readerarea, div.reading-content, dll) atau fallback ke seluruh halaman.
    """
    name = "generic"

    CHAPTER_LINK_PATTERN = re.compile(r'(chapter|ch|c|ep)/?.*?\d', re.IGNORECASE)
    CHAPTER_NUM_PATTERN = re.compile(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', re.IGNORECASE)

    def get_title(self, driver, series_url):
        driver.get(series_url)
        time.sleep(3.5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        candidates = [
            soup.select_one('h1'),
            soup.select_one('h1.font-bold'),
            soup.select_one('h1.text-3xl'),
            soup.select_one('.series-title'),
            soup.select_one('.series-name'),
            soup.select_one('meta[property="og:title"]'),
        ]
        for tag in candidates:
            if tag:
                txt = tag.get('content') or tag.get_text(strip=True)
                if txt and len(txt) > 3 and "BETA SITE" not in txt.upper():
                    return self.core.clean_name(txt)

        slug = series_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug)) or "Comic_Download"

    def get_chapters(self, driver, series_url):
        driver.get(series_url)
        time.sleep(4)

        try:
            container = WebDriverWait(driver, 12).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.overflow-y-auto, div[class*='chapter'], div.list, ul, section")
                )
            )
        except Exception:
            container = driver.find_element(By.TAG_NAME, "body")

        last_height = driver.execute_script("return arguments[0].scrollHeight", container)
        for attempt in range(25):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
            time.sleep(1.2)
            new_height = driver.execute_script("return arguments[0].scrollHeight", container)
            if new_height == last_height and attempt > 5:
                break
            last_height = new_height
            print(f"  Scroll {attempt+1}/25", end="\r")
        print()
        time.sleep(3.5)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if self.CHAPTER_LINK_PATTERN.search(href):
                full_url = urllib.parse.urljoin(series_url, href)
                if full_url not in links:
                    links.append(full_url)

        links = [u for u in links if self.get_chapter_num(u) > 0]
        links.sort(key=self.get_chapter_num)
        return links

    def get_chapter_num(self, chap_url):
        m = self.CHAPTER_NUM_PATTERN.search(chap_url)
        return float(m.group(1)) if m else -1

    def get_chapter_images(self, driver, chap_url):
        driver.get(chap_url)
        time.sleep(3)

        for _ in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.9)

        driver.execute_script("""
            document.querySelectorAll('img').forEach(img => {
                let src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.srcset?.split(' ')[0] || img.src;
                if (src) img.src = src;
            });
        """)
        time.sleep(2.5)

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        reader_container = soup.select_one(
            'div#readerarea, div.reading-content, div.reader-area, div.chapter-content, section#chapter'
        )
        if not reader_container:
            reader_container = soup

        imgs = reader_container.find_all('img')
        valid_imgs = []
        end_marker = 'EndDesign.webp'
        for img in imgs:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original')
            if not src:
                continue
            src = urllib.parse.urljoin(chap_url, src.strip())
            if end_marker in src:
                break
            if 'storage/media/' in src or re.search(r'page[-_]\d+', src, re.I) or 'chapter' in src.lower():
                if not any(kw in src.lower() for kw in
                           ['banner', 'logo', 'ads', 'icon', 'thumb', 'social', 'discord', 'related', 'cover']):
                    valid_imgs.append(src)

        return list(dict.fromkeys(valid_imgs))


class DemonicScansAdapter(BaseSiteAdapter):
    """Adapter khusus demonicscans.org (dari DemonicDownloader)."""
    name = "demonicscans.org"
    BASE_URL = "https://demonicscans.org"

    def get_title(self, driver, series_url):
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
                    return self.core.clean_name(txt)

        slug = series_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug))

    def get_chapters(self, driver, series_url):
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
        for a in soup.find_all('a', href=True, class_='chplinks'):
            href = a['href']
            if 'chaptered.php' in href and '&chapter=' in href:
                links.add(urllib.parse.urljoin(self.BASE_URL, href))

        return sorted([u for u in links if self.get_chapter_num(u) > 0], key=self.get_chapter_num)

    def get_chapter_num(self, chap_url):
        m = re.search(r'&chapter=([\d.]+)', chap_url, re.I)
        return float(m.group(1)) if m else -1

    def get_chapter_images(self, driver, chap_url):
        driver.get(chap_url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        collected = []
        for img in soup.find_all('img', class_='imgholder'):
            src = img.get('src')
            if src:
                src = src.replace('demoniclibs.com', 'librarydm.com')
                collected.append(src)
        return collected


# Daftar adapter khusus per-domain. Tambahkan situs baru di sini.
SITE_ADAPTERS = {
    'demonicscans.org': DemonicScansAdapter,
}


def resolve_adapter(core, url):
    domain = urllib.parse.urlparse(url).netloc.lower().replace('www.', '')
    for key, adapter_cls in SITE_ADAPTERS.items():
        if key in domain:
            print(f"[INFO] Situs dikenali: {adapter_cls.name} (adapter khusus dipakai)")
            return adapter_cls(core)
    print(f"[INFO] Situs '{domain}' tidak punya adapter khusus, memakai mode GENERIC.")
    return GenericSiteAdapter(core)


# ============================================================
# ORKESTRASI DOWNLOAD (dipakai untuk semua adapter)
# ============================================================

class UniversalComicDownloader:
    def __init__(self, max_workers=6):
        self.core = ComicDownloaderCore(max_workers=max_workers)

    def download_chapter(self, adapter, chap_url, base_folder):
        driver = None
        chap_num = adapter.get_chapter_num(chap_url)
        chap_label = f"{chap_num:g}" if chap_num > 0 else "unknown"
        folder = os.path.join(base_folder, f"Chapter_{chap_label:0>7}" if chap_num > 0 else "Chapter_Unknown")
        os.makedirs(folder, exist_ok=True)

        try:
            print(f"\n[Chapter {chap_label}] Memuat halaman...")
            driver = self.core.get_driver(enable_images=True)
            valid_imgs = adapter.get_chapter_images(driver, chap_url)

            if not valid_imgs:
                print(f"  Chapter {chap_label}: tidak ada gambar ditemukan.")
                return 0

            print(f"  Chapter {chap_label}: {len(valid_imgs)} halaman ditemukan, mulai download...")

            tasks = []
            for idx, src in enumerate(valid_imgs, 1):
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                path = os.path.join(folder, f"{idx:03d}{ext}")
                tasks.append((src, path))

            stats = self.core.download_images(tasks)
            print(f"  Chapter {chap_label} selesai: {stats['ok']}/{len(valid_imgs)} halaman "
                  f"({stats['size']/1048576:.1f} MB)")
            return stats['ok']
        except Exception as e:
            print(f"\n[ERROR] Download chapter {chap_label} gagal: {e}")
            return 0
        finally:
            if driver:
                driver.quit()

    def run(self, series_url, start_ch=1, end_ch=9999):
        adapter = resolve_adapter(self.core, series_url)

        # --- Ambil judul ---
        driver = self.core.get_driver(enable_images=False)
        try:
            title = adapter.get_title(driver, series_url)
        finally:
            driver.quit()

        base_folder = os.path.join("Komik", title)
        os.makedirs(base_folder, exist_ok=True)
        print(f"[INFO] Judul  : {title}")
        print(f"[INFO] Folder : {base_folder}\n")

        # --- Ambil daftar chapter ---
        driver = self.core.get_driver(enable_images=False)
        try:
            chapters = adapter.get_chapters(driver, series_url)
        finally:
            driver.quit()

        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan. Coba cek URL, atau situs butuh adapter khusus baru.")
            return

        to_download = []
        for url in chapters:
            num = adapter.get_chapter_num(url)
            if num > 0 and start_ch <= num <= end_ch:
                to_download.append((num, url))
        to_download.sort(key=lambda x: x[0])

        if not to_download:
            print(f"[WARN] Tidak ada chapter dalam range {start_ch}-{end_ch}.")
            return

        print(f"[INFO] Akan mendownload {len(to_download)} chapter (range {start_ch}-{end_ch})\n")

        total_pages = 0
        for idx, (num, url) in enumerate(to_download, 1):
            print(f"[{idx}/{len(to_download)}] Chapter {num:g}")
            total_pages += self.download_chapter(adapter, url, base_folder)
            time.sleep(2)

        print(f"\n{'='*50}")
        print("SELESAI")
        print(f"Total halaman berhasil : {total_pages}")
        print(f"Lokasi file            : {os.path.abspath(base_folder)}")
        print(f"{'='*50}")


if __name__ == "__main__":
    print("Universal Comic Downloader")
    print("Mendukung situs apapun (mode generic), plus adapter khusus untuk: "
          + ", ".join(SITE_ADAPTERS.keys()))
    print("-" * 50)

    url = input("Masukkan URL series: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    start_input = input("Chapter mulai (default 1): ").strip()
    end_input = input("Chapter akhir (default semua): ").strip()

    start = float(start_input) if start_input else 1
    end = float(end_input) if end_input else 9999

    downloader = UniversalComicDownloader()
    downloader.run(url, start, end)