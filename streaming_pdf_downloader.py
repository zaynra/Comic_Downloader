"""
Streaming PDF Downloader
========================
Same download logic as comic_downloader.py (junk filtering, adapters,
cleanup) + same convert logic as convert.py (canvas, PDF merge).
After each chapter downloads, immediately converts to PDF and deletes images.

Usage:
    python streaming_pdf_downloader.py
"""

import os
import sys
import time
import re
import json
import shutil
import tempfile
import threading
import subprocess
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from bs4 import BeautifulSoup, NavigableString
from webdriver_manager.chrome import ChromeDriverManager

from PIL import Image
from pypdf import PdfWriter

from notification_manager import TelegramNotifier

Image.MAX_IMAGE_PIXELS = None
bot = TelegramNotifier()

JUNK_SIGNATURES_FILE = "junk_signatures.json"
_junk_signatures_lock = Lock()

try:
    import imagehash
    _IMAGEHASH_AVAILABLE = True
except ImportError:
    _IMAGEHASH_AVAILABLE = False

try:
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False


def _load_junk_signatures(path=JUNK_SIGNATURES_FILE):
    with _junk_signatures_lock:
        if not os.path.exists(path):
            return {"keywords": [], "hashes": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"keywords": list(data.get("keywords", [])), "hashes": list(data.get("hashes", []))}
        except Exception:
            return {"keywords": [], "hashes": []}


def _save_junk_signatures(signatures, path=JUNK_SIGNATURES_FILE):
    with _junk_signatures_lock:
        try:
            keywords = sorted(set(signatures.get("keywords", [])))[:500]
            hashes = list(dict.fromkeys(signatures.get("hashes", [])))[:500]
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"keywords": keywords, "hashes": hashes}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] Gagal menyimpan {path}: {e}")


# ============================================================
# EXACT COPY: ComicDownloaderCore from comic_downloader.py
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
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max_workers, pool_maxsize=max_workers * 2, max_retries=2,
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
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
            options.add_argument("--log-level=3")
            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            options.add_experimental_option("useAutomationExtension", False)
            prefs = {"profile.managed_default_content_settings.images": 1 if enable_images else 2}
            options.add_experimental_option("prefs", prefs)
            service = Service(ChromeDriverManager().install(), log_output=subprocess.DEVNULL)
            if os.name == "nt":
                service.creationflags = subprocess.CREATE_NO_WINDOW
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            print(f"[ERROR] Setup driver gagal: {e}")
            sys.exit(1)

    def clean_name(self, s):
        if not s:
            return "Unknown"
        return re.sub(r'[<>:"/\\|?*]', '', re.sub(r'\s+', ' ', str(s))).strip()[:80]

    def download_img(self, img_url, filepath, min_size=10240):
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
                return False, 0
            return True, size
        except Exception:
            return False, 0

    def _download_batch(self, tasks):
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {executor.submit(self.download_img, u, p): (u, p) for u, p in tasks}
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                results[task] = future.result()
        return results

    def download_images(self, tasks):
        self.stats = {'ok': 0, 'fail': 0, 'size': 0}
        results = self._download_batch(tasks)
        failed_tasks = [task for task, (ok, _) in results.items() if not ok]
        if failed_tasks:
            time.sleep(1.5)
            retry_results = self._download_batch(failed_tasks)
            results.update(retry_results)
        for ok, size in results.values():
            if ok:
                self.stats['ok'] += 1
                self.stats['size'] += size
            else:
                self.stats['fail'] += 1
        return self.stats


# ============================================================
# EXACT COPY: GenericSiteAdapter from comic_downloader.py
# ============================================================

class GenericSiteAdapter:
    name = "generic"
    CHAPTER_LINK_PATTERN = re.compile(r'(chapter|ch|c|ep)/?.*?\d', re.IGNORECASE)
    CHAPTER_NUM_PATTERN = re.compile(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', re.IGNORECASE)
    BLOCKED_KEYWORDS = (
        'banner', 'logo', 'icon', 'favicon', 'avatar', 'ads', 'advert',
        'recommend', 'thumbnail', 'thumb', 'cover', 'header', 'footer',
        'social', 'discord', 'comment', 'profile', 'placeholder',
        'loading', 'spinner', 'related', 'sidebar', 'widget', 'popup',
        'promo', 'sponsor', 'emoji', 'twemoji', 'smilies', 'wp-smiley',
        'patreon', 'kofi', 'ko-fi', 'buymeacoffee', 'trakteer', 'saweria',
        'disqus', 'gravatar', 'avatar', 'telegram', 'whatsapp', 'twitter',
        'facebook', 'instagram', 'youtube', 'gallery-thumb', 'series-thumb',
        'nextchapter', 'next-chapter', 'prevchapter', 'prev-chapter',
        'navigation', 'nav-chapter', 'notice', 'watermark-logo',
    )
    END_MARKERS = (
        'enddesign', 'end-design', 'end_design', 'endofchapter', 'end-chapter',
        'end_chapter', 'chapterend', 'endpage', 'end-page', 'endofpage',
        'thankyou', 'thank-you', 'supportus', 'support-us', 'followus',
        'follow-us', 'joinourdiscord', 'read-next', 'readnext', 'closing',
        'outro', 'omake-end',
    )
    TEXT_END_MARKERS = (
        'end chapter', 'end of chapter', 'the end', 'thanks for reading',
        'thank you for reading', 'read next', 'recommendation',
        'recommended for you', 'you may also like', 'you might also like',
        'join discord', 'join our discord', 'support us',
        'support the author', 'buy me a coffee', 'leave a comment',
        'comments (', 'next chapter', 'previous chapter',
    )
    VALID_IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')
    MIN_PORTRAIT_RATIO = 0.9
    CHAPTER_IMAGE_PATTERNS = re.compile(
        r'/(chapters|chapter|pages?)/.*?\.(webp|jpg|jpeg|png)', re.IGNORECASE
    )
    READER_SELECTORS = (
        "div#readerarea, div.reading-content, div.reader-area, "
        "div.chapter-content, section#chapter, div.chapter-images, "
        "div.container-chapter-reader, div.page-break, "
        "div[class*='reader'], div[id*='reader'], main"
    )
    EXCLUDE_SECTION_SELECTORS = (
        "div.comments, div#comments, div#disqus_thread, div.disqus, "
        "section.comments, div.fb-comments, div.sharethis, "
        "div.share-buttons, div.social-share, div.socmed, "
        "div.related, div.related-posts, div.you-may-like, "
        "div.recommended, div.rekomendasi, aside, nav, footer, header, "
        "div.navigation, div.chapter-nav, div.chapternav, "
        "div.next-prev, div.pagination, div.sidebar, div.widget, "
        "div.ads, div.advertisement, ins.adsbygoogle, "
        "div.patreon, div.kofi, div.discord-widget, div.support-us, "
        "img.emoji, img.wp-smiley, "
        "[class*='comment'], [id*='comment'], [class*='recommend'], "
        "[id*='recommend'], [class*='related'], [id*='related'], "
        "[class*='support'], [id*='support'], [class*='discord'], "
        "[id*='discord'], [class*='next-chapter'], [class*='prev-chapter'], "
        "[class*='chapter-nav'], [class*='share'], [class*='social'], "
        "[class*='sidebar'], [id*='sidebar'], [class*='ads'], [id*='ads'], "
        "[class*='footer'], [id*='footer'], [class*='header'], [id*='header']"
    )

    def __init__(self, core: ComicDownloaderCore):
        self.core = core

    def get_title(self, driver, series_url):
        driver.get(series_url)
        time.sleep(3.5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = [
            soup.select_one('h1'), soup.select_one('h1.font-bold'),
            soup.select_one('h1.text-3xl'), soup.select_one('.series-title'),
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

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        driver.get(chap_url)
        time.sleep(3)

        last_height = driver.execute_script("return document.body.scrollHeight")
        stable_rounds = 0
        for _ in range(60):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.8)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                stable_rounds += 1
                if stable_rounds >= 3:
                    break
            else:
                stable_rounds = 0
            last_height = new_height

        if cancel_event and cancel_event.is_set():
            return []

        driver.execute_script("window.scrollTo(0, 0)")
        time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)

        if cancel_event and cancel_event.is_set():
            return []

        driver.execute_script("""
            document.querySelectorAll('img').forEach(img => {
                let src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.srcset?.split(' ')[0] || img.src;
                if (src) img.src = src;
            });
            document.querySelectorAll('img').forEach(img => {
                if (img.classList.contains('emoji') || img.classList.contains('wp-smiley')) {
                    img.remove();
                } else if (img.naturalWidth > 0 && img.naturalWidth < 150 && img.naturalHeight > 0 && img.naturalHeight < 150) {
                    img.remove();
                } else {
                    if (img.naturalWidth) img.setAttribute('data-natural-width', img.naturalWidth);
                    if (img.naturalHeight) img.setAttribute('data-natural-height', img.naturalHeight);
                }
            });
        """)
        time.sleep(2.5)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        for tag in soup.select(self.EXCLUDE_SECTION_SELECTORS):
            tag.decompose()

        reader_container = soup.select_one(self.READER_SELECTORS) or soup

        candidates = self._extract_sequential_images(reader_container, chap_url)
        candidates = list(dict.fromkeys(candidates))
        candidates = self._filter_domain_outliers(candidates)
        return candidates

    def _extract_sequential_images(self, reader_container, base_url):
        urls = []
        valid_count = 0
        for node in reader_container.descendants:
            if isinstance(node, NavigableString):
                text = str(node).strip().lower()
                if text and len(text) <= 120:
                    if any(marker in text for marker in self.TEXT_END_MARKERS):
                        break
                continue
            if getattr(node, 'name', None) != 'img':
                continue
            img = node
            src = (img.get('src') or img.get('data-src') or
                   img.get('data-lazy-src') or img.get('data-original') or
                   img.get('data-lazy') or img.get('data-url'))
            if not src:
                continue
            url = urllib.parse.urljoin(base_url, src.strip())
            low = url.lower()
            if any(marker in low for marker in self.END_MARKERS):
                break
            is_valid = self._is_valid_page_image(url)
            if not is_valid:
                if valid_count > 0:
                    break
                continue

            is_strong_positive = bool(self.CHAPTER_IMAGE_PATTERNS.search(url))

            if not is_strong_positive:
                width = self._to_float(img.get('data-natural-width'))
                height = self._to_float(img.get('data-natural-height'))
                if width and height and width > 0:
                    ratio = height / width
                    if ratio < self.MIN_PORTRAIT_RATIO:
                        if valid_count > 0:
                            break
                        continue

            if not is_strong_positive and self._matches_known_junk_keyword(url):
                if valid_count > 0:
                    break
                continue
            urls.append(url)
            valid_count += 1
        return urls

    @staticmethod
    def _to_float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _matches_known_junk_keyword(url):
        keywords = _load_junk_signatures().get("keywords", [])
        if not keywords:
            return False
        low = url.lower()
        return any(kw in low for kw in keywords)

    def _is_valid_page_image(self, url):
        low = url.lower()
        path = urllib.parse.urlparse(low).path
        basename = os.path.basename(path)
        for kw in self.BLOCKED_KEYWORDS:
            if re.search(rf'(?:^|[^a-z0-9]){re.escape(kw)}(?:[^a-z0-9]|$)', basename):
                return False
        if self.CHAPTER_IMAGE_PATTERNS.search(low):
            return True
        ext = os.path.splitext(path)[1]
        if ext and ext not in self.VALID_IMG_EXT:
            return False
        if not ext and not re.search(r'page[-_]?\d+|/\d{2,4}[./_-]|chapter', low):
            return False
        return True

    def _filter_domain_outliers(self, urls):
        if len(urls) < 3:
            return urls
        domains = [urllib.parse.urlparse(u).netloc for u in urls]
        common_domain, count = Counter(domains).most_common(1)[0]
        if count < len(urls) * 0.5:
            return urls
        filtered = []
        for u in urls:
            if urllib.parse.urlparse(u).netloc == common_domain:
                filtered.append(u)
                continue
            if re.search(r'page[-_]?\d+', u, re.I):
                filtered.append(u)
        return filtered

    def cleanup_chapter_folder(self, folder, tail_check=5):
        if not os.path.isdir(folder):
            return 0
        image_files = sorted(
            f for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in self.VALID_IMG_EXT
        )
        if not image_files:
            return 0
        cut_index = None
        junk_keywords = []
        junk_hashes = []
        known = _load_junk_signatures()
        known_hashes = set(known.get("hashes", []))
        start = max(0, len(image_files) - tail_check)
        for i in range(start, len(image_files)):
            filename = image_files[i]
            filepath = os.path.join(folder, filename)
            is_junk, reason, phash = self._inspect_possible_junk_file(filepath, known_hashes)
            if is_junk:
                cut_index = i
                junk_keywords.append(reason)
                if phash:
                    junk_hashes.append(phash)
                break
        if cut_index is None:
            return 0
        removed = image_files[cut_index:]
        for filename in removed:
            try:
                os.remove(os.path.join(folder, filename))
            except OSError:
                pass
        kept = image_files[:cut_index]
        self._renumber_folder(folder, kept)
        self._trim_manifest(folder, len(kept))
        if junk_keywords or junk_hashes:
            signatures = _load_junk_signatures()
            signatures["keywords"].extend(k for k in junk_keywords if k)
            signatures["hashes"].extend(junk_hashes)
            _save_junk_signatures(signatures)
        return len(removed)

    def _inspect_possible_junk_file(self, filepath, known_hashes):
        filename = os.path.basename(filepath).lower()
        for kw in self.BLOCKED_KEYWORDS + self.END_MARKERS:
            if kw in filename:
                return True, kw, None
        try:
            with Image.open(filepath) as img:
                width, height = img.size
                is_landscape_ish = width > 0 and (height / width) < self.MIN_PORTRAIT_RATIO
                phash = None
                if _IMAGEHASH_AVAILABLE:
                    try:
                        phash = str(imagehash.phash(img))
                    except Exception:
                        phash = None
                if phash and phash in known_hashes:
                    return True, None, phash
                if is_landscape_ish:
                    if _OCR_AVAILABLE:
                        try:
                            ocr_text = pytesseract.image_to_string(img).strip().lower()
                        except Exception:
                            ocr_text = ""
                        if ocr_text and any(marker in ocr_text for marker in self.TEXT_END_MARKERS):
                            return True, None, phash
                    return True, None, phash
        except Exception:
            return False, None, None
        return False, None, None

    @staticmethod
    def _renumber_folder(folder, filenames):
        temp_names = []
        for filename in filenames:
            src = os.path.join(folder, filename)
            tmp = os.path.join(folder, f"__tmp__{filename}")
            try:
                os.rename(src, tmp)
                temp_names.append((tmp, os.path.splitext(filename)[1]))
            except OSError:
                pass
        for idx, (tmp, ext) in enumerate(temp_names, 1):
            dest = os.path.join(folder, f"{idx:03d}{ext}")
            try:
                os.rename(tmp, dest)
            except OSError:
                pass

    @staticmethod
    def _trim_manifest(folder, keep_count):
        manifest_path = os.path.join(folder, "chapter_manifest.json")
        if not os.path.exists(manifest_path):
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            trimmed = manifest[:keep_count]
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, indent=4, ensure_ascii=False)
        except Exception:
            pass


class DemonicScansAdapter(GenericSiteAdapter):
    name = "demonicscans.org"
    BASE_URL = "https://demonicscans.org"

    def get_title(self, driver, series_url):
        driver.get(series_url)
        time.sleep(4)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = [
            soup.select_one('h1'), soup.select_one('h2.series-title'),
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

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        if cancel_event and cancel_event.is_set():
            return []
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


SITE_ADAPTERS = {'demonicscans.org': DemonicScansAdapter}


def resolve_adapter(core, url):
    domain = urllib.parse.urlparse(url).netloc.lower().replace('www.', '')
    for key, adapter_cls in SITE_ADAPTERS.items():
        if key in domain:
            print(f"[INFO] Situs dikenali: {adapter_cls.name}")
            return adapter_cls(core)
    print(f"[INFO] Situs '{domain}' memakai mode GENERIC.")
    return GenericSiteAdapter(core)


# ============================================================
# EXACT COPY: convert.py logic
# ============================================================

OUTPUT_FOLDER_CANDIDATES = ["Result", "PDF", "Output"]
RESULT_FOLDER_NAME = OUTPUT_FOLDER_CANDIDATES[0]
CHAPTER_PDF_PREFIX = "Chapter_"
MAX_PDF_PAGE_HEIGHT = 65000
IMAGE_RESOLUTION = 300.0
IMAGE_QUALITY = 95
JPEG_SUBSAMPLING = 2
JPEG_MIN_QUALITY = 82


def _adaptive_jpeg_quality(width, height):
    megapixels = (width * height) / 1_000_000
    if megapixels > 150: return JPEG_MIN_QUALITY
    if megapixels > 60: return 86
    if megapixels > 20: return 90
    return IMAGE_QUALITY


def natural_sort_key(name):
    parts = re.split(r'(\d+)', name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


def extract_chapter_number(name):
    m = re.search(r'(\d+(?:\.\d+)?)', name)
    return float(m.group(1)) if m else None


def format_chapter_label(num):
    if float(num).is_integer():
        return f"{int(num):04d}"
    integer_part, _, decimal_part = f"{num:g}".partition('.')
    return f"{int(integer_part):04d}.{decimal_part}"


def get_chapter_label(name):
    num = extract_chapter_number(name)
    return format_chapter_label(num) if num is not None else sanitize_filename(name)


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
    return image.resize((ref_width, round(orig_h * (ref_width / orig_w))), Image.LANCZOS)


def compute_reference_size(image_paths):
    widths = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                widths.append(img.size[0])
        except Exception:
            continue
    return max(widths) if widths else None


def collect_images_from_folder(folder):
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    image_files = [f for f in files if is_image_file(os.path.join(folder, f))]
    image_files.sort(key=lambda f: natural_sort_key(f))
    return [os.path.join(folder, f) for f in image_files]


def _compute_scaled_heights(image_paths, ref_width):
    valid_paths, heights = [], []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                orig_w, orig_h = img.size
            new_h = round(orig_h * (ref_width / orig_w))
            valid_paths.append(path)
            heights.append(new_h)
        except Exception as e:
            print(f"      [x] Rusak/skip: {os.path.basename(path)} -> {e}")
    return valid_paths, heights, sum(heights)


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
    use_width, use_heights = ref_width, heights
    if total_height > max_height:
        scale = max_height / total_height
        use_width = max(1, int(ref_width * scale))
        use_heights = [max(1, round(h * scale)) for h in heights]
        total_height = sum(use_heights)
        print("      [!] Satu gambar terlalu tinggi untuk 1 halaman PDF, diskalakan turun agar muat.")
    canvas = Image.new("RGB", (use_width, total_height), (255, 255, 255))
    y, pasted = 0, 0
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
                try: img.close()
                except: pass
    return canvas, pasted


def _merge_pdfs(temp_pdf_paths, output_path):
    writer = PdfWriter()
    try:
        for temp_path in temp_pdf_paths:
            writer.append(temp_path)
        try: writer.compress_content_streams()
        except: pass
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
        canvas, pasted = _paste_chunk_canvas(valid_paths, heights, ref_width, MAX_PDF_PAGE_HEIGHT, 0, len(valid_paths))
        print()
        success = True
        try:
            canvas.save(output_path, "PDF", resolution=IMAGE_RESOLUTION,
                        quality=_adaptive_jpeg_quality(*canvas.size),
                        optimize=True, progressive=True, subsampling=JPEG_SUBSAMPLING)
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
    print(f"   [i] '{label}' sangat panjang (~{total_height}px), dipecah jadi {len(chunks)} halaman PDF.")
    with tempfile.TemporaryDirectory(prefix="comic_pdf_super_") as temp_dir:
        temp_pdf_paths, pasted_total, idx_offset = [], 0, 0
        for ci, (paths_chunk, heights_chunk) in enumerate(chunks, 1):
            canvas, pasted = _paste_chunk_canvas(paths_chunk, heights_chunk, ref_width, MAX_PDF_PAGE_HEIGHT, idx_offset, len(valid_paths))
            idx_offset += len(paths_chunk)
            pasted_total += pasted
            temp_path = os.path.join(temp_dir, f"superpage_{ci:03d}.pdf")
            try:
                canvas.save(temp_path, "PDF", resolution=IMAGE_RESOLUTION,
                            quality=_adaptive_jpeg_quality(*canvas.size),
                            optimize=True, progressive=True, subsampling=JPEG_SUBSAMPLING)
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


def get_result_dir(source_dir):
    for candidate in OUTPUT_FOLDER_CANDIDATES:
        candidate_path = os.path.join(source_dir, candidate)
        if os.path.isdir(candidate_path):
            return candidate_path
    result_dir = os.path.join(source_dir, RESULT_FOLDER_NAME)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir


# ============================================================
# ORCHESTRATOR - follows comic_downloader.py run() logic exactly
# ============================================================

class StreamingPDFDownloader:
    def __init__(self, max_workers=6, driver_holder=None):
        self.core = ComicDownloaderCore(max_workers=max_workers)
        self._unknown_counter = 0
        self._cancel_event = threading.Event()
        self._driver_holder = driver_holder or {}

    def cancel(self):
        self._cancel_event.set()
        driver = self._driver_holder.get("driver")
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    def format_chapter_folder(self, chap_num):
        if chap_num is None or chap_num <= 0:
            self._unknown_counter += 1
            return f"Chapter_Unknown_{self._unknown_counter}"
        if float(chap_num).is_integer():
            return f"{int(chap_num):04d}"
        integer_part, _, decimal_part = f"{chap_num:g}".partition('.')
        return f"{int(integer_part):04d}.{decimal_part}"

    def write_chapter_manifest(self, folder, valid_imgs):
        manifest = [{"page": idx, "url": src} for idx, src in enumerate(valid_imgs, 1)]
        try:
            with open(os.path.join(folder, "chapter_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"      [!] Gagal menulis chapter_manifest.json: {e}")

    def _get_completed_nums(self, base_folder):
        numbers = set()
        if os.path.isdir(base_folder):
            for entry in os.listdir(base_folder):
                if entry == "Result":
                    continue
                entry_path = os.path.join(base_folder, entry)
                if os.path.isdir(entry_path):
                    m = re.search(r'(\d+(?:\.\d+)?)', entry)
                    if m:
                        numbers.add(float(m.group(1)))
        result_folder = os.path.join(base_folder, "Result")
        if os.path.isdir(result_folder):
            for entry in os.listdir(result_folder):
                if entry.lower().endswith(".pdf"):
                    stem = os.path.splitext(entry)[0]
                    m = re.search(r'(\d+(?:\.\d+)?)', stem)
                    if m:
                        numbers.add(float(m.group(1)))
        return numbers

    def run(self, series_url, start_ch=1, end_ch=9999, base_dir="Komik", progress_callback=None):
        self._cancel_event.clear()
        self._unknown_counter = 0

        adapter = resolve_adapter(self.core, series_url)

        driver = self.core.get_driver(enable_images=False)
        try:
            title = adapter.get_title(driver, series_url)
        finally:
            driver.quit()

        base_folder = os.path.join(base_dir, title)
        os.makedirs(base_folder, exist_ok=True)
        result_dir = get_result_dir(base_folder)

        print(f"[INFO] Mode     : Streaming PDF (download -> convert -> hapus gambar)")
        print(f"[INFO] Judul    : {title}")
        print(f"[INFO] Folder   : {base_folder}")
        print(f"[INFO] PDF Dir  : {result_dir}")
        print(f"[INFO] Range    : {start_ch} - {end_ch}\n")

        driver = self.core.get_driver(enable_images=False)
        try:
            chapters = adapter.get_chapters(driver, series_url)
        finally:
            driver.quit()

        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        completed_nums = self._get_completed_nums(base_folder)

        to_download = []
        skipped_nums = []
        for url in chapters:
            num = adapter.get_chapter_num(url)
            if num <= 0 or not (start_ch <= num <= end_ch):
                continue
            if num in completed_nums:
                skipped_nums.append(num)
                continue
            to_download.append((num, url))

        seen = set()
        deduped = []
        for num, url in to_download:
            if num not in seen:
                seen.add(num)
                deduped.append((num, url))
        to_download = sorted(deduped, key=lambda x: x[0])

        if skipped_nums:
            preview = ", ".join(f"{n:g}" for n in sorted(skipped_nums)[:10])
            more = f" (+{len(skipped_nums) - 10} lagi)" if len(skipped_nums) > 10 else ""
            print(f"[INFO] Melewati {len(skipped_nums)} chapter yang sudah ada: {preview}{more}\n")

        if not to_download:
            print(f"[WARN] Tidak ada chapter baru dalam range {start_ch}-{end_ch}.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        print(f"[INFO] Akan mendownload + convert {len(to_download)} chapter\n")

        try:
            bot.start(title, start_ch, end_ch)
        except Exception:
            pass

        run_start_time = time.time()
        success_count = 0
        failed_count = 0
        cancelled_flag = False
        pdfs_created = []

        shared_driver = self.core.get_driver(enable_images=True)
        self._driver_holder["driver"] = shared_driver

        try:
            for idx, (num, url) in enumerate(to_download, 1):
                if self._cancel_event.is_set():
                    print("[INFO] Proses dibatalkan oleh perintah sistem.")
                    cancelled_flag = True
                    break

                label = f"{num:g}"
                print(f"[{idx}/{len(to_download)}] Chapter {label}")

                folder_name = self.format_chapter_folder(num)
                folder = os.path.join(base_folder, folder_name)
                os.makedirs(folder, exist_ok=True)

                result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}

                try:
                    valid_imgs = adapter.get_chapter_images(shared_driver, url, cancel_event=self._cancel_event)
                except WebDriverException as e:
                    if self._cancel_event.is_set():
                        cancelled_flag = True
                        break
                    print(f"   [!] Browser bermasalah ({e.__class__.__name__}), membuat ulang session...")
                    try: shared_driver.quit()
                    except: pass
                    shared_driver = self.core.get_driver(enable_images=True)
                    try:
                        valid_imgs = adapter.get_chapter_images(shared_driver, url, cancel_event=self._cancel_event)
                    except Exception as e2:
                        print(f"      [!] Chapter {label} gagal total: {e2}")
                        result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}
                        valid_imgs = None

                if valid_imgs is None:
                    pass
                elif self._cancel_event.is_set():
                    cancelled_flag = True
                    break
                elif not valid_imgs:
                    result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}
                else:
                    self.write_chapter_manifest(folder, valid_imgs)
                    tasks = []
                    for i, src in enumerate(valid_imgs, 1):
                        ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                        path = os.path.join(folder, f"{i:03d}{ext}")
                        tasks.append((src, path))
                    stats = self.core.download_images(tasks)
                    total = len(valid_imgs)
                    success = stats['ok'] > 0
                    if success and hasattr(adapter, "cleanup_chapter_folder"):
                        try: adapter.cleanup_chapter_folder(folder)
                        except: pass
                    result = {"success": success, "pages": stats['ok'], "total": total, "size_mb": stats['size'] / 1048576}

                if self._cancel_event.is_set():
                    cancelled_flag = True
                    break

                if not result["success"]:
                    print(f"   [retry] Percobaan ulang 1x...")
                    time.sleep(2)
                    try:
                        valid_imgs = adapter.get_chapter_images(shared_driver, url, cancel_event=self._cancel_event)
                        if valid_imgs:
                            self.write_chapter_manifest(folder, valid_imgs)
                            tasks = []
                            for i, src in enumerate(valid_imgs, 1):
                                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                                path = os.path.join(folder, f"{i:03d}{ext}")
                                tasks.append((src, path))
                            stats = self.core.download_images(tasks)
                            total = len(valid_imgs)
                            success = stats['ok'] > 0
                            if success and hasattr(adapter, "cleanup_chapter_folder"):
                                try: adapter.cleanup_chapter_folder(folder)
                                except: pass
                            result = {"success": success, "pages": stats['ok'], "total": total, "size_mb": stats['size'] / 1048576}
                    except Exception as e:
                        print(f"      [!] Retry gagal: {e}")

                if self._cancel_event.is_set():
                    cancelled_flag = True
                    break

                if result["success"]:
                    print(f"      Downloaded: {result['pages']}/{result['total']} pages, {result['size_mb']:.1f} MB")

                    chapter_label = get_chapter_label(folder_name)
                    output_name = format_chapter_pdf_filename(chapter_label)
                    output_path = os.path.join(result_dir, output_name)

                    if os.path.isfile(output_path):
                        print(f"      PDF sudah ada, skip convert")
                    else:
                        print(f"      Converting ke PDF...")
                        ok = convert_chapter_to_pdf(folder, output_path)
                        if ok and os.path.isfile(output_path):
                            pdf_size = os.path.getsize(output_path) / 1048576
                            print(f"      PDF tersimpan: {output_name} ({pdf_size:.1f} MB)")
                            pdfs_created.append(output_path)
                        else:
                            print(f"      [WARN] Convert gagal")

                    # Delete chapter folder (images)
                    try:
                        shutil.rmtree(folder)
                        print(f"      Gambar dihapus")
                    except Exception as e:
                        print(f"      [WARN] Gagal hapus folder: {e}")

                    success_count += 1
                else:
                    print(f"      Failed")
                    failed_count += 1

                if progress_callback:
                    try:
                        progress_callback(idx, len(to_download), f"Chapter {label:g}", result)
                    except Exception:
                        pass

                time.sleep(2)

        finally:
            try: shared_driver.quit()
            except: pass

        elapsed = time.time() - run_start_time
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        durasi = f"{h}h {m}m {s}s" if h > 0 else (f"{m}m {s}s" if m > 0 else f"{s}s")

        print(f"\n{'='*50}")
        print(f"Selesai dalam {durasi}")
        print(f"Berhasil : {success_count}")
        print(f"Gagal    : {failed_count}")
        print(f"PDF      : {len(pdfs_created)} file")
        print(f"Folder   : {result_dir}")
        print(f"{'='*50}")

        all_pdfs = []
        if os.path.isdir(result_dir):
            for f in sorted(os.listdir(result_dir)):
                if f.lower().endswith(".pdf"):
                    all_pdfs.append(os.path.join(result_dir, f))

        try:
            bot.finish(title, len(to_download), success_count, failed_count, durasi)
        except Exception:
            pass

        return {
            "total": len(to_download), "success": success_count, "failed": failed_count,
            "cancelled": cancelled_flag, "pdfs": all_pdfs,
        }


if __name__ == "__main__":
    print("Streaming PDF Downloader")
    print("Download -> Convert PDF -> Hapus Gambar")
    print("-" * 50)

    url = input("Masukkan URL series: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    dl = StreamingPDFDownloader()

    start_input = input("Chapter mulai (default 1): ").strip()
    end_input = input("Chapter akhir (default semua): ").strip()

    start = float(start_input) if start_input else 1
    end = float(end_input) if end_input else 9999

    dl.run(url, start_ch=start, end_ch=end)
