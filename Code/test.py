from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

class AsuraDownloader:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.max_workers = 6
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
            options.add_argument("--window-size=1280,800")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            prefs = {"profile.managed_default_content_settings.images": 1 if enable_images else 2}
            options.add_experimental_option("prefs", prefs)

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            print(f"ERROR saat setup driver: {e}")
            sys.exit(1)

    def clean_name(self, s):
        if not s:
            return "Unknown"
        return re.sub(r'[<>:"/\\|?*]', '', re.sub(r'\s+', ' ', str(s))).strip()[:80]

    def get_title(self, url):
        driver = None
        try:
            driver = self.get_driver(enable_images=False)
            driver.get(url)
            time.sleep(3.5)
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            candidates = [
                soup.select_one('h1'),
                soup.select_one('h1.font-bold'),
                soup.select_one('h1.text-3xl'),
                soup.select_one('.series-title'),
                soup.select_one('meta[property="og:title"]'),
            ]
            for tag in candidates:
                if tag:
                    txt = tag.get('content') or tag.get_text(strip=True)
                    if txt and len(txt) > 5 and "BETA SITE" not in txt.upper():
                        return self.clean_name(txt)
            return "Comic_Download"
        except Exception as e:
            print(f"Error ambil title: {e}")
            return "Comic_Download"
        finally:
            if driver:
                driver.quit()

    def get_chapters(self, series_url):
        driver = None
        try:
            print("Memuat halaman series dan scroll chapter list...")
            driver = self.get_driver(enable_images=False)
            driver.get(series_url)
            time.sleep(4)

            try:
                container = WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.overflow-y-auto, div[class*='chapter'], div.list, ul, section"))
                )
                print("Container chapter ditemukan.")
            except:
                container = driver.find_element(By.TAG_NAME, "body")
                print("Gunakan body sebagai fallback scroll.")

            last_height = driver.execute_script("return arguments[0].scrollHeight", container)
            for attempt in range(25):
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
                time.sleep(1.2)
                new_height = driver.execute_script("return arguments[0].scrollHeight", container)
                if new_height == last_height and attempt > 5:
                    break
                last_height = new_height
                print(f"Scroll {attempt+1}/25", end="\r")

            print("\nTunggu render selesai...")
            time.sleep(3.5)

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if re.search(r'(chapter|ch|c|ep)/?.*?\d', href, re.IGNORECASE):
                    full_url = urllib.parse.urljoin(series_url, href)
                    if full_url not in links:
                        links.append(full_url)

            def get_num(u):
                m = re.search(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', u, re.I)
                return float(m.group(1)) if m else -1

            links = [u for u in links if get_num(u) > 0]
            links.sort(key=get_num)

            print(f"Ditemukan {len(links)} chapter valid.")
            return links
        except Exception as e:
            print(f"Error ambil daftar chapter: {e}")
            return []
        finally:
            if driver:
                driver.quit()

    def download_img(self, img_url, filepath):
        try:
            r = self.session.get(img_url, timeout=12, stream=True)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
            size = os.path.getsize(filepath)
            with self.lock:
                self.stats['ok'] += 1
                self.stats['size'] += size
            return True
        except Exception:
            with self.lock:
                self.stats['fail'] += 1
            return False

    def download_chapter(self, chap_url, base_folder):
        driver = None
        try:
            m = re.search(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', chap_url, re.I)
            chap_num = m.group(1) if m else "unknown"

            folder = os.path.join(base_folder, f"Chapter_{chap_num.zfill(4)}")
            os.makedirs(folder, exist_ok=True)

            print(f"Memproses Chapter {chap_num}...")
            driver = self.get_driver(enable_images=True)
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

            imgs = []
            selectors = [
                'div#readerarea img',
                '.reading-content img',
                'img[src*="asuracomic.net/storage"]',
                'img[src*=".webp"], img[src*=".jpg"], img[src*=".png"]'
            ]
            for sel in selectors:
                found = soup.select(sel)
                if found:
                    imgs.extend(found)
                    break

            if not imgs:
                imgs = soup.find_all('img')

            valid_imgs = []
            for img in imgs:
                src = (
                    img.get('src') or
                    img.get('data-src') or
                    img.get('data-lazy-src') or
                    img.get('data-original')
                )
                if not src:
                    continue
                src = urllib.parse.urljoin(chap_url, src.strip())
                if 'EndDesign.webp' in src:
                    break
                if any(kw in src.lower() for kw in ['banner', 'logo', 'ads', 'icon', 'thumb', 'social']):
                    continue
                if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    valid_imgs.append(src)

            valid_imgs = list(dict.fromkeys(valid_imgs))  # remove duplicate

            if not valid_imgs:
                print(f"Chapter {chap_num}: Tidak ada gambar valid ditemukan.")
                return 0

            print(f"Chapter {chap_num}: {len(valid_imgs)} halaman akan di-download")

            self.stats = {'ok': 0, 'fail': 0, 'size': 0}
            tasks = []
            for idx, src in enumerate(valid_imgs, 1):
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                path = os.path.join(folder, f"{idx:03d}{ext}")
                tasks.append((src, path))

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self.download_img, url, pth) for url, pth in tasks]
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    if completed % 5 == 0 or completed == len(tasks):
                        print(f"  Progress: {completed}/{len(tasks)} ({self.stats['ok']} berhasil)", end="\r")

            print(f"\nChapter {chap_num} selesai: {self.stats['ok']}/{len(valid_imgs)} halaman ({self.stats['size']/1048576:.1f} MB)")
            return self.stats['ok']
        except Exception as e:
            print(f"Error download chapter {chap_num}: {e}")
            return 0
        finally:
            if driver:
                driver.quit()

    def run(self, series_url, start_ch=1, end_ch=9999):
        title = self.get_title(series_url)
        base_folder = os.path.join("Komik", title)
        os.makedirs(base_folder, exist_ok=True)
        print(f"Folder simpan: {base_folder}\n")

        chapters = self.get_chapters(series_url)
        if not chapters:
            print("Gagal menemukan chapter. Coba non-headless atau cek koneksi/situs.")
            return

        to_download = []
        for url in chapters:
            m = re.search(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', url, re.I)
            if m:
                num = float(m.group(1))
                if start_ch <= num <= end_ch:
                    to_download.append((num, url))

        to_download.sort(key=lambda x: x[0])
        print(f"Akan mendownload {len(to_download)} chapter (range {start_ch} - {end_ch})\n")

        total_pages = 0
        for idx, (num, url) in enumerate(to_download, 1):
            print(f"[{idx}/{len(to_download)}] Chapter {num:.1f}")
            pages = self.download_chapter(url, base_folder)
            total_pages += pages
            time.sleep(2)  # jeda antar chapter

        print(f"\n=== SELESAI ===")
        print(f"Total halaman berhasil: {total_pages}")
        print(f"Lokasi: {os.path.abspath(base_folder)}")


if __name__ == "__main__":
    print("Asura Downloader - Versi Diperbaiki (Maret 2026)")
    print("-" * 50)

    url = input("Masukkan URL series: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    start_input = input("Chapter mulai (default 1): ").strip()
    end_input = input("Chapter akhir (default semua): ").strip()

    start = float(start_input) if start_input else 1
    end = float(end_input) if end_input else 9999

    downloader = AsuraDownloader()
    downloader.run(url, start, end)