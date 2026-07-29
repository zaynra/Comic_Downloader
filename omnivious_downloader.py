"""
Omnivious Downloader - Multi-Site Comic/Manga/Doujin downloader
================================================================
Download comic chapter or gallery -> convert to PDF immediately -> delete images.

Supported sites:
  - DemonicScans.org    (chapter-based)
  - Toonily.com         (chapter-based)
  - Comix.to            (chapter-based)
  - Asuracomic.net      (chapter-based)
  - Hentaifox.com       (gallery-list)
  - Cin.cx              (gallery-list)
  - Generic fallback    (any site with heuristic detection)

Usage:
    python omnivious_downloader.py
    Then enter URL when prompted.

Or import and use:
    from omnivious_downloader import StreamingPDFDownloader
    dl = StreamingPDFDownloader()
    dl.run("https://example.com/comic/title", start_ch=1, end_ch=50)
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
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault('WDM_LOG', '0')
os.environ.setdefault('WDM_LOG_LEVEL', '0')
os.environ.setdefault('WDM_PRINT_FIRST_LINE', 'False')

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


class ComicDownloaderCore:
    def __init__(self, max_workers=6):
        self.headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/134.0.0.0 Safari/537.36'),
            'Referer': 'https://nhentai.net/',
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
        except Exception as e:
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


class BaseSiteAdapter:
    name = "generic"
    PER_ITEM_SERIES = False

    def __init__(self, core: ComicDownloaderCore):
        self.core = core

    def get_title(self, driver, url):
        raise NotImplementedError

    def get_chapters(self, driver, url):
        raise NotImplementedError

    def get_chapter_num(self, url):
        raise NotImplementedError

    def get_chapter_images(self, driver, url, cancel_event=None):
        raise NotImplementedError

    def get_item_title(self, item_url):
        return None


class GenericSiteAdapter(BaseSiteAdapter):
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
        time.sleep(1.0)

        for _ in range(10):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.3)

        time.sleep(1.0)

        for round_num in range(3):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("""
                document.querySelectorAll('img').forEach(img => {
                    let src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.srcset?.split(' ')[0] || img.src;
                    if (src && !img.src.startsWith(src)) img.src = src;
                    if (src) img.loading = 'eager';
                });
            """)
            time.sleep(1.5)

        if cancel_event and cancel_event.is_set():
            return []

        time.sleep(3.0)

        driver.execute_script("""
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
        time.sleep(2.0)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        for tag in soup.select(self.EXCLUDE_SECTION_SELECTORS):
            tag.decompose()

        reader_container = soup.select_one(self.READER_SELECTORS) or soup

        candidates = self._extract_sequential_images(reader_container, chap_url)
        candidates = self._dedupe_keep_order(candidates)
        candidates = self._filter_domain_outliers(candidates)

        return candidates

    def _extract_sequential_images(self, reader_container, base_url):
        urls = []
        valid_count = 0
        invalid_streak = 0
        MAX_INVALID_STREAK = 5

        for node in reader_container.descendants:
            if isinstance(node, NavigableString):
                text = str(node).strip().lower()
                if text and len(text) <= 120:
                    if any(marker in text for marker in self.TEXT_END_MARKERS):
                        if valid_count > 0:
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
                if valid_count > 0:
                    break
                continue

            if not self._is_valid_page_image(url):
                if valid_count > 0:
                    invalid_streak += 1
                    if invalid_streak >= MAX_INVALID_STREAK:
                        break
                continue

            width = self._to_float(img.get('data-natural-width'))
            height = self._to_float(img.get('data-natural-height'))
            if width and height and width > 0:
                ratio = height / width
                if ratio < self.MIN_PORTRAIT_RATIO:
                    if valid_count > 0:
                        invalid_streak += 1
                        if invalid_streak >= MAX_INVALID_STREAK:
                            break
                    continue

            if self._matches_known_junk_keyword(url):
                if valid_count > 0:
                    invalid_streak += 1
                    if invalid_streak >= MAX_INVALID_STREAK:
                        break
                continue

            urls.append(url)
            valid_count += 1
            invalid_streak = 0

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

    def _dedupe_keep_order(self, urls):
        return list(dict.fromkeys(urls))

    def _filter_domain_outliers(self, urls):
        if len(urls) < 3:
            return urls
        from collections import Counter
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
        except Exception as e:
            print(f"      [!] Gagal memangkas chapter_manifest.json: {e}")


class DemonicScansAdapter(BaseSiteAdapter):
    name = "demonicscans.org"
    BASE_URL = "https://demonicscans.org"

    IMAGE_DOMAINS = [
        'demoniclibs.com',
        'librarydm.com',
        'cdn.demoniclibs.com',
        'cdn.librarydm.com',
    ]

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

    def get_chapter_images(self, driver, chap_url, cancel_event=None, max_retries=1):
        for attempt in range(max_retries + 1):
            if cancel_event and cancel_event.is_set():
                return []

            if attempt > 0:
                print(f"      [RETRY {attempt}] Muat ulang halaman...")
                driver.get(chap_url)
                time.sleep(3)

            images = self._extract_images_with_scroll(driver, chap_url, cancel_event)
            if images:
                return images

            if attempt < max_retries:
                print(f"      [RETRY {attempt+1}] 0 gambar, coba refresh + scroll ulang...")
                time.sleep(2)

        print(f"      [WARN] Gagal mengambil gambar setelah {max_retries+1}x percobaan.")
        return []

    def _extract_images_with_scroll(self, driver, chap_url, cancel_event):
        driver.get(chap_url)
        time.sleep(3)

        last_height = driver.execute_script("return document.body.scrollHeight")
        stable_rounds = 0
        for _ in range(40):
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

        if not (cancel_event and cancel_event.is_set()):
            driver.execute_script("""
                document.querySelectorAll('img').forEach(img => {
                    let src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.dataset.lazy || img.dataset.url || img.src;
                    if (src && src !== '') img.src = src;
                    img.loading = 'eager';
                });
            """)
            time.sleep(2)

        if not (cancel_event and cancel_event.is_set()):
            driver.execute_script("window.scrollTo(0, 0)")
            time.sleep(0.5)
            for _ in range(15):
                if cancel_event and cancel_event.is_set():
                    return []
                driver.execute_script("window.scrollBy(0, 600)")
                time.sleep(0.4)

        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        collected = []

        for img in soup.find_all('img', class_='imgholder'):
            src = self._resolve_src(img)
            if src:
                collected.append(src)

        if collected:
            return self._fix_image_urls(collected)

        for selector in ['.reading-content', '.reader-area', '.chapter-content',
                         '.chapter-container', '.entry-content', '.text-left',
                         'div[class*="chapter"]', 'div[class*="reader"]',
                         'div[class*="content"]']:
            container = soup.select_one(selector)
            if container:
                for img in container.find_all('img'):
                    src = self._resolve_src(img)
                    if src:
                        collected.append(src)
                if collected:
                    return self._fix_image_urls(collected)

        for img in soup.find_all('img'):
            src = self._resolve_src(img)
            if src:
                domain = urllib.parse.urlparse(src).netloc.lower()
                if any(d in domain for d in self.IMAGE_DOMAINS):
                    collected.append(src)
                elif 'page' in src.lower() or 'chapter' in src.lower():
                    ext = os.path.splitext(urllib.parse.urlparse(src).path)[1].lower()
                    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'):
                        collected.append(src)

        if collected:
            return self._fix_image_urls(collected)

        for img in soup.find_all('img'):
            src = self._resolve_src(img)
            if src:
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1].lower()
                if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                    collected.append(src)

        if collected:
            return self._fix_image_urls(collected)

        return []

    def _resolve_src(self, img_tag):
        src = (img_tag.get('src') or img_tag.get('data-src') or
               img_tag.get('data-lazy-src') or img_tag.get('data-original') or
               img_tag.get('data-lazy') or img_tag.get('data-url') or '')
        return src.strip() if src else None

    def _fix_image_urls(self, urls):
        fixed = []
        for url in urls:
            url = url.replace('demoniclibs.com', 'librarydm.com')
            fixed.append(url)
        return fixed


class ToonilyAdapter(BaseSiteAdapter):
    name = "toonily.com"
    BASE_URL = "https://toonily.com"

    def _handle_age_verification(self, driver):
        try:
            modal_selectors = ["#adult_modal", ".modal", ".modal-content"]
            for selector in modal_selectors:
                modal = driver.find_elements(By.CSS_SELECTOR, selector)
                if modal and modal[0].is_displayed():
                    for btn_selector in [".modal .btn-primary", ".modal-footer .btn",
                                         "button:contains('18+')", "button:contains('Yes')",
                                         "button:contains('Enter')"]:
                        try:
                            if ':contains' in btn_selector:
                                js_sel = btn_selector.split(':contains')[0]
                                els = driver.execute_script(f"""
                                    return Array.from(document.querySelectorAll('{js_sel}')).filter(
                                        el => el.textContent.includes('18+') || el.textContent.includes('Yes')
                                    );
                                """)
                                if els:
                                    driver.execute_script("arguments[0].click();", els[0])
                                    time.sleep(2)
                                    break
                            else:
                                el = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, btn_selector))
                                )
                                driver.execute_script("arguments[0].click();", el)
                                time.sleep(2)
                                break
                        except Exception:
                            continue
                    break
            driver.execute_script("""
                var overlays = document.querySelectorAll('.age-gate, .age-verification, .overlay, #adult_modal, .modal');
                overlays.forEach(function(o) { o.style.display = 'none'; });
                document.body.classList.remove('modal-open');
            """)
            time.sleep(1)
        except Exception:
            pass

    def get_title(self, driver, series_url):
        driver.get(self.BASE_URL + "/")
        self._handle_age_verification(driver)
        driver.get(series_url)
        self._handle_age_verification(driver)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = [
            soup.select_one('h1.entry-title'),
            soup.select_one('.post-title h1'),
            soup.select_one('.post-title'),
            soup.select_one('h1'),
            soup.select_one('meta[property="og:title"]'),
        ]
        for tag in candidates:
            if tag:
                txt = tag.get('content') or tag.get_text(strip=True)
                if txt and len(txt) > 2:
                    return self.core.clean_name(txt)
        slug = series_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug))

    def get_chapters(self, driver, series_url):
        driver.get(self.BASE_URL + "/")
        self._handle_age_verification(driver)
        driver.get(series_url)
        self._handle_age_verification(driver)
        time.sleep(3)

        last_height = driver.execute_script("return document.body.scrollHeight")
        no_change = 0
        while no_change < 3:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                no_change += 1
            else:
                no_change = 0
            last_height = new_height

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = []
        chapter_selectors = [
            '.listing-chapters_wrap ul.main.version-chap li a',
            '.listing-chapters_wrap ul.main li a',
            'a[href*="/chapter-"]', 'a[href*="/chapter/"]',
            '.wp-manga-chapter a',
        ]
        seen = set()
        for selector in chapter_selectors:
            for a in soup.select(selector):
                href = a.get('href', '')
                if href and ('/chapter-' in href or '/chapter/' in href or '/ch-' in href):
                    full = urllib.parse.urljoin(series_url, href)
                    if full not in seen:
                        seen.add(full)
                        links.append(full)
            if links:
                break

        def extract_num(url):
            m = re.search(r'/(?:chapter|ch)[-/](\d+(?:\.\d+)?)', url)
            return float(m.group(1)) if m else 0

        links = [u for u in links if extract_num(u) > 0]
        links.sort(key=extract_num)
        return links

    def get_chapter_num(self, chap_url):
        m = re.search(r'/(?:chapter|ch)[-/](\d+(?:\.\d+)?)', chap_url, re.I)
        return float(m.group(1)) if m else -1

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        driver.get(self.BASE_URL + "/")
        self._handle_age_verification(driver)
        driver.get(chap_url)
        self._handle_age_verification(driver)
        time.sleep(3)

        last_height = driver.execute_script("return document.body.scrollHeight")
        no_change = 0
        for _ in range(20):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                no_change += 1
                if no_change >= 3:
                    break
            else:
                no_change = 0
            last_height = new_height

        if cancel_event and cancel_event.is_set():
            return []

        driver.execute_script("""
            document.querySelectorAll('img[data-wpfc-original-src]').forEach(img => {
                img.src = img.getAttribute('data-wpfc-original-src');
            });
            document.querySelectorAll('img[data-src]').forEach(img => {
                img.src = img.getAttribute('data-src');
            });
            document.querySelectorAll('img[data-lazy-src]').forEach(img => {
                img.src = img.getAttribute('data-lazy-src');
            });
            document.querySelectorAll('img.lazy, img[loading="lazy"]').forEach(img => {
                if (img.dataset.src) img.src = img.dataset.src;
                img.loading = 'eager';
            });
            document.querySelectorAll('img').forEach(img => {
                if (img.src && !img.complete) {
                    var src = img.src;
                    img.src = '';
                    img.src = src;
                }
            });
        """)
        time.sleep(4)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        for tag in soup.select(self.EXCLUDE_SECTION_SELECTORS):
            tag.decompose()

        reader_selectors = ['.reading-content', '#readerarea', '.entry-content',
                            '.chapter-content', '.content', '.text-left']
        reader = None
        for sel in reader_selectors:
            reader = soup.select_one(sel)
            if reader:
                break
        if not reader:
            reader = soup

        images = []
        skip_kw = ['icon', 'logo', 'avatar', 'thumb', 'banner', 'ads',
                   'discord', 'header', 'footer', 'sidebar', 'comment',
                   'social', 'share', 'promo', 'loading', 'spinner']

        for img in reader.find_all('img'):
            src = (img.get('src') or img.get('data-wpfc-original-src') or
                   img.get('data-src') or img.get('data-lazy-src') or
                   img.get('data-original'))
            if not src:
                continue
            if src.startswith("data:image") and len(src) < 1000:
                continue
            if not src.startswith(('http://', 'https://', 'data:')):
                src = urllib.parse.urljoin(chap_url, src)
            low = src.lower()
            if any(kw in low for kw in skip_kw):
                continue
            ext = os.path.splitext(urllib.parse.urlparse(low).path)[1]
            if ext and ext not in self.VALID_IMG_EXT:
                continue
            images.append(src)

        return list(dict.fromkeys(images))


class ComixAdapter(BaseSiteAdapter):
    name = "comix.to"
    BASE_URL = "https://comix.to"

    def get_title(self, driver, series_url):
        driver.get(series_url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = [
            soup.select_one('h1'), soup.select_one('.title'),
            soup.select_one('meta[property="og:title"]'),
        ]
        for tag in candidates:
            if tag:
                txt = tag.get('content') or tag.get_text(strip=True)
                if txt and len(txt) > 2:
                    return self.core.clean_name(txt)
        slug = series_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug))

    def get_chapters(self, driver, series_url):
        driver.get(series_url)
        time.sleep(5)
        last_h = driver.execute_script("return document.body.scrollHeight")
        for i in range(25):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.2)
            new_h = driver.execute_script("return document.body.scrollHeight")
            if new_h == last_h and i > 5:
                break
            last_h = new_h
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/chapter/' in href or re.search(r'/ch[-/]?\d+', href, re.I):
                links.add(urllib.parse.urljoin(self.BASE_URL, href))
        return sorted([u for u in links if self.get_chapter_num(u) > 0], key=self.get_chapter_num)

    def get_chapter_num(self, chap_url):
        m = re.search(r'/(?:chapter|ch)[-/]?(\d+(?:\.\d+)?)', chap_url, re.I)
        return float(m.group(1)) if m else -1

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        driver.get(chap_url)
        time.sleep(4)

        last_height = driver.execute_script("return document.body.scrollHeight")
        stable = 0
        for _ in range(40):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.8)
            new_h = driver.execute_script("return document.body.scrollHeight")
            if new_h == last_height:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            last_height = new_h

        if cancel_event and cancel_event.is_set():
            return []

        driver.execute_script("""
            document.querySelectorAll('img').forEach(img => {
                let src = img.dataset.src || img.dataset.lazySrc || img.srcset?.split(' ')[0] || img.src;
                if (src && src !== '') {
                    if (!img.src || img.src.includes('data:')) img.src = src;
                }
                img.loading = 'eager';
            });
        """)
        time.sleep(3)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        for tag in soup.select(self.EXCLUDE_SECTION_SELECTORS):
            tag.decompose()

        reader = (soup.select_one('.chapter-content, .reading-content, #readerarea, .reader-area, [class*="reader"], main') or soup)
        images = []
        for img in reader.find_all('img'):
            src = (img.get('src') or img.get('data-src') or img.get('data-lazy-src'))
            if not src or src.startswith('data:'):
                continue
            if not src.startswith('http'):
                src = urllib.parse.urljoin(chap_url, src)
            low = src.lower()
            if any(kw in low for kw in ['icon', 'logo', 'avatar', 'banner', 'ads']):
                continue
            ext = os.path.splitext(urllib.parse.urlparse(low).path)[1]
            if ext and ext not in self.VALID_IMG_EXT:
                continue
            images.append(src)

        return list(dict.fromkeys(images))


class AsuraScansAdapter(BaseSiteAdapter):
    name = "asuracomic.net"
    BASE_URL = "https://asuracomic.net"

    def get_title(self, driver, series_url):
        driver.get(series_url)
        time.sleep(4)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = [
            soup.select_one('h1'), soup.select_one('h1.font-bold'),
            soup.select_one('h1.text-3xl'), soup.select_one('.series-title'),
            soup.select_one('meta[property="og:title"]'),
        ]
        for tag in candidates:
            if tag:
                txt = tag.get('content') or tag.get_text(strip=True)
                if txt and len(txt) > 3:
                    return self.core.clean_name(txt)
        slug = series_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug))

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
        for i in range(25):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
            time.sleep(1.2)
            new_h = driver.execute_script("return arguments[0].scrollHeight", container)
            if new_h == last_height and i > 5:
                break
            last_height = new_h
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if re.search(r'(chapter|ch|c|ep)/?.*?\d', href, re.I):
                full = urllib.parse.urljoin(series_url, href)
                if full not in links:
                    links.append(full)
        links = [u for u in links if self.get_chapter_num(u) > 0]
        links.sort(key=self.get_chapter_num)
        return links

    def get_chapter_num(self, chap_url):
        m = re.search(r'(?:chapter|ch|c|ep)[/-]?(\d+(?:\.\d+)?)', chap_url, re.I)
        return float(m.group(1)) if m else -1

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        driver.get(chap_url)
        time.sleep(3)
        for _ in range(12):
            if cancel_event and cancel_event.is_set():
                return []
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.9)

        if cancel_event and cancel_event.is_set():
            return []

        driver.execute_script("""
            document.querySelectorAll('img').forEach(img => {
                let src = img.dataset.src || img.dataset.lazySrc || img.dataset.original || img.srcset?.split(' ')[0] || img.src;
                if (src) img.src = src;
            });
        """)
        time.sleep(2.5)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        reader_selectors = "div#readerarea, div.reading-content, div.reader-area, div.chapter-content, section#chapter, main"
        reader = soup.select_one(reader_selectors)
        if not reader:
            reader = soup

        images = []
        end_marker = 'EndDesign.webp'
        for img in reader.find_all('img'):
            src = (img.get('src') or img.get('data-src') or
                   img.get('data-lazy-src') or img.get('data-original'))
            if not src:
                continue
            src = urllib.parse.urljoin(chap_url, src.strip())
            if end_marker in src:
                break
            low = src.lower()
            if 'storage/media/' in low or re.search(r'page[-_]\d+', low) or 'chapter' in low:
                if not any(kw in low for kw in ['banner', 'logo', 'ads', 'icon', 'thumb', 'social', 'discord']):
                    images.append(src)

        return list(dict.fromkeys(images))


class HentaifoxAdapter(BaseSiteAdapter):
    name = "hentaifox.com"
    PER_ITEM_SERIES = True

    def get_title(self, driver, list_url):
        driver.get(list_url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        title_tag = soup.select_one('h1') or soup.select_one('.page-title') or soup.select_one('title')
        if title_tag:
            txt = title_tag.get_text(strip=True)
            if txt:
                return self.core.clean_name(txt)
        slug = list_url.rstrip('/').split('/')[-1]
        return self.core.clean_name(urllib.parse.unquote(slug))

    def get_chapters(self, driver, list_url):
        all_galleries = []
        current_url = list_url
        max_pages = 10

        for page in range(1, max_pages + 1):
            driver.get(current_url)
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            found = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if re.search(r'/gallery/(\d+)', href):
                    full = urllib.parse.urljoin(list_url, href)
                    if full not in all_galleries:
                        found.append(full)

            if not found:
                break

            all_galleries.extend(found)

            next_link = soup.select_one('.pagination a:contains("Next")')
            if next_link:
                next_href = next_link.get('href', '')
                if next_href.startswith('//'):
                    current_url = 'https:' + next_href
                elif next_href.startswith('/'):
                    current_url = urllib.parse.urljoin(list_url, next_href)
                elif next_href.startswith('http'):
                    current_url = next_href
                else:
                    break
            else:
                break

        return list(dict.fromkeys(all_galleries))

    def get_chapter_num(self, gallery_url):
        m = re.search(r'/gallery/(\d+)', gallery_url)
        return int(m.group(1)) if m else -1

    def get_item_title(self, gallery_url):
        try:
            resp = self.core.session.get(gallery_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            title_tag = (soup.select_one('h1') or
                         soup.select_one('meta[property="og:title"]') or
                         soup.select_one('title'))
            if title_tag:
                txt = title_tag.get('content') or title_tag.get_text(strip=True)
                if txt:
                    txt = txt.replace(' - HentaiFox', '').strip()
                    if txt:
                        return self.core.clean_name(txt)
        except Exception:
            pass
        return f"Gallery_{self.get_chapter_num(gallery_url)}"

    def get_chapter_images(self, driver, gallery_url, cancel_event=None):
        try:
            resp = self.core.session.get(gallery_url, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            print(f"      [ERROR] Gagal fetch gallery page: {e}")
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        load_dir = None
        load_id = None
        load_pages = None

        for inp in soup.find_all('input', type='hidden'):
            name = inp.get('name', '')
            if name == 'load_dir':
                load_dir = inp.get('value', '')
            elif name == 'load_id':
                load_id = inp.get('value', '')
            elif name == 'load_pages':
                load_pages = inp.get('value', '')

        if not load_dir or not load_id or not load_pages:
            print(f"      [ERROR] Gagal extract gallery data dari halaman")
            return []

        try:
            num_pages = int(load_pages)
        except ValueError:
            num_pages = 0

        if num_pages <= 0:
            return []

        ext_map = {'w': 'webp', 'j': 'jpg', 'p': 'png', 'g': 'gif'}
        image_urls = []

        cover_img = soup.select_one('.cover img')
        cdn_domain = "i3"
        if cover_img:
            cover_src = cover_img.get('src', '')
            m = re.search(r'https://(i\d?)\.hentaifox\.com', cover_src)
            if m:
                cdn_domain = m.group(1)

        g_th_script = soup.find('script', text=re.compile(r'var g_th\s*='))
        if g_th_script:
            m = re.search(r"var g_th\s*=\s*\$\.parseJSON\('(.+?)'\)", g_th_script.string)
            if m:
                try:
                    g_th_data = json.loads(m.group(1).replace("'", ""))
                    for page_num in range(1, num_pages + 1):
                        val = g_th_data.get(str(page_num), '')
                        ext_code = val.split(',')[0] if val else 'w'
                        ext = ext_map.get(ext_code, 'webp')
                        img_url = f"https://{cdn_domain}.hentaifox.com/{load_dir}/{load_id}/{page_num}.{ext}"
                        image_urls.append(img_url)
                    return image_urls
                except Exception:
                    pass

        for page_num in range(1, num_pages + 1):
            img_url = f"https://{cdn_domain}.hentaifox.com/{load_dir}/{load_id}/{page_num}.webp"
            image_urls.append(img_url)

        return image_urls


class CinCxAdapter(BaseSiteAdapter):
    name = "cin.cx"
    PER_ITEM_SERIES = True
    NHENTAI_API = "https://nhentai.net/api/v2"

    def get_title(self, driver, search_url):
        parsed = urllib.parse.urlparse(search_url)
        qs = urllib.parse.parse_qs(parsed.query)
        query = qs.get('query', qs.get('tags', ['']))[0]
        if query:
            return self.core.clean_name(urllib.parse.unquote(query))
        return "Cin.cx Search"

    def get_chapters(self, driver, search_url):
        parsed = urllib.parse.urlparse(search_url)
        qs = urllib.parse.parse_qs(parsed.query)

        query = qs.get('query', [''])[0].strip()
        tags = qs.get('tags', [''])[0].strip()
        page = int(qs.get('page', ['1'])[0])

        search_q = query if query else tags
        if not search_q:
            print("[ERROR] Tidak ada query search ditemukan di URL.")
            return []

        all_results = []
        current_page = page
        max_api_pages = 10

        while current_page <= max_api_pages:
            try:
                api_url = f"{self.NHENTAI_API}/search?query={urllib.parse.quote(search_q)}&page={current_page}"
                resp = self.core.session.get(api_url, timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
                results = data.get('result', [])
                if not results:
                    break
                for r in results:
                    gid = r.get('id')
                    if gid:
                        all_results.append(f"https://nhentai.net/api/v2/galleries/{gid}")
                total_pages = data.get('num_pages', 0)
                if current_page >= total_pages:
                    break
                current_page += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"[WARN] Gagal fetch search page {current_page}: {e}")
                break

        return all_results

    def get_chapter_num(self, gallery_url):
        m = re.search(r'/galleries/(\d+)', gallery_url)
        return int(m.group(1)) if m else -1

    def get_item_title(self, gallery_url):
        try:
            resp = self.core.session.get(gallery_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            title = (data.get('title', {}).get('english') or
                     data.get('title', {}).get('japanese') or
                     data.get('title', {}).get('pretty', ''))
            if title:
                return self.core.clean_name(title)
        except Exception:
            pass
        return f"Gallery_{self.get_chapter_num(gallery_url)}"

    def get_chapter_images(self, driver, gallery_url, cancel_event=None):
        try:
            resp = self.core.session.get(gallery_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"      [ERROR] Gagal fetch gallery detail: {e}")
            return []

        media_id = data.get('media_id')
        pages = data.get('pages', [])
        if not media_id or not pages:
            return []

        image_urls = []
        for page in pages:
            page_num = page.get('number', 1)
            ext_map = {'j': 'jpg', 'p': 'png', 'g': 'gif', 'w': 'webp'}
            ext = ext_map.get(page.get('t', 'j'), 'jpg')
            img_url = f"https://i.nhentai.net/galleries/{media_id}/{page_num}.{ext}"
            image_urls.append(img_url)

        return image_urls


SITE_ADAPTERS = {
    'demonicscans.org': DemonicScansAdapter,
    'toonily.com': ToonilyAdapter,
    'comix.to': ComixAdapter,
    'asuracomic.net': AsuraScansAdapter,
    'hentaifox.com': HentaifoxAdapter,
    'cin.cx': CinCxAdapter,
}


def resolve_adapter(core, url):
    domain = urllib.parse.urlparse(url).netloc.lower().replace('www.', '')
    for key, adapter_cls in SITE_ADAPTERS.items():
        if key in domain:
            return adapter_cls(core)
    return GenericSiteAdapter(core)


OUTPUT_FOLDER_CANDIDATES = ["Result", "PDF", "Output"]
RESULT_FOLDER_NAME = OUTPUT_FOLDER_CANDIDATES[0]
CHAPTER_PDF_PREFIX = "Chapter_"
IMAGE_RESOLUTION = 300.0
IMAGE_QUALITY = 95
MAX_PDF_PAGE_HEIGHT = 65000


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
    if num is not None:
        return format_chapter_label(num)
    return sanitize_filename(name)


def format_chapter_pdf_filename(chapter_label):
    return f"{CHAPTER_PDF_PREFIX}{chapter_label}.pdf"


def _extract_base_title(title):
    t = title.strip()
    t = re.sub(r'^\[.*?\]\s*', '', t)
    t = re.sub(r'\s*\[.*?\]$', '', t)
    t = re.sub(r'\s+\d+(?:\s+.*)?$', '', t)
    return t.strip()


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


def get_result_dir(source_dir):
    for candidate in OUTPUT_FOLDER_CANDIDATES:
        candidate_path = os.path.join(source_dir, candidate)
        if os.path.isdir(candidate_path):
            return candidate_path
    result_dir = os.path.join(source_dir, RESULT_FOLDER_NAME)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir


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
            canvas.save(output_path, "PDF", resolution=IMAGE_RESOLUTION, quality=IMAGE_QUALITY)
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

    with tempfile.TemporaryDirectory(prefix="comic_pdf_super_") as temp_dir:
        temp_pdf_paths = []
        pasted_total = 0
        idx_offset = 0
        for ci, (paths_chunk, heights_chunk) in enumerate(chunks, 1):
            canvas, pasted = _paste_chunk_canvas(
                paths_chunk, heights_chunk, ref_width, MAX_PDF_PAGE_HEIGHT, idx_offset, len(valid_paths),
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
        print()
        if not temp_pdf_paths:
            print(f"   [x] Semua halaman super gagal disimpan untuk '{label}'.")
            return False
        success = _merge_pdfs(temp_pdf_paths, output_path)

    if success:
        print(f"   Saved: {os.path.relpath(output_path, os.path.dirname(os.path.dirname(output_path)))}")
    return success


def convert_chapter_to_pdf(chapter_dir, output_path):
    chapter_name = os.path.basename(chapter_dir)
    image_paths = collect_images_from_folder(chapter_dir)
    if not image_paths:
        print(f"   [!] Tidak ada gambar di '{chapter_name}', dilewati.")
        return False
    ref_width = compute_reference_size(image_paths)
    return build_long_strip_pdf(image_paths, ref_width, output_path, chapter_name)


class StreamingPDFDownloader:
    def __init__(self, max_workers=6):
        self.core = ComicDownloaderCore(max_workers=max_workers)
        self._unknown_counter = 0
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def format_chapter_folder(self, chap_num):
        if chap_num is None or chap_num <= 0:
            self._unknown_counter += 1
            return f"Chapter_Unknown_{self._unknown_counter}"
        if float(chap_num).is_integer():
            return f"{int(chap_num):04d}"
        integer_part, _, decimal_part = f"{chap_num:g}".partition('.')
        return f"{int(integer_part):04d}.{decimal_part}"

    def _convert_and_delete(self, chapter_folder, result_dir, chapter_label):
        output_name = format_chapter_pdf_filename(chapter_label)
        output_path = os.path.join(result_dir, output_name)

        if os.path.isfile(output_path):
            self._cleanup_folder(chapter_folder)
            return True, output_path

        try:
            ok = convert_chapter_to_pdf(chapter_folder, output_path)
            if ok and os.path.isfile(output_path):
                self._cleanup_folder(chapter_folder)
                return True, output_path
            else:
                return False, None
        except Exception as e:
            print(f"      [ERROR] Convert error: {e}")
            return False, None

    def _cleanup_folder(self, folder):
        try:
            if os.path.isdir(folder):
                shutil.rmtree(folder)
        except Exception as e:
            print(f"      [WARN] Gagal hapus folder {folder}: {e}")

    def _get_completed_nums(self, base_folder):
        numbers = set()

        if os.path.isdir(base_folder):
            for entry in os.listdir(base_folder):
                if entry in ("Result", ".DS_Store"):
                    continue
                entry_path = os.path.join(base_folder, entry)
                if os.path.isdir(entry_path):
                    m = re.search(r'(\d+(?:\.\d+)?)', entry)
                    if m:
                        numbers.add(float(m.group(1)))

        result_dir = os.path.join(base_folder, "Result")
        if os.path.isdir(result_dir):
            for f in os.listdir(result_dir):
                if f.lower().endswith(".pdf"):
                    m = re.search(r'(\d+(?:\.\d+)?)', os.path.splitext(f)[0])
                    if m:
                        numbers.add(float(m.group(1)))
        return numbers

    @staticmethod
    def _extract_slug(url):
        slug = url.rstrip('/').split('/')[-1]
        slug = urllib.parse.unquote(slug)
        slug = re.sub(r'-[0-9a-fA-F]{5,}$', '', slug)
        return slug

    @staticmethod
    def _normalize(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())

    @staticmethod
    def _guess_display_name(slug):
        words = re.split(r'[-_]+', slug)
        return " ".join(w.capitalize() for w in words if w)

    def detect_existing_progress(self, url, base_dir="Komik"):
        label_width = 17
        slug = self._extract_slug(url)
        norm_slug = self._normalize(slug)
        guessed_name = self._guess_display_name(slug) or slug

        match_folder = None
        match_name = None
        if os.path.isdir(base_dir):
            for name in os.listdir(base_dir):
                full_path = os.path.join(base_dir, name)
                if os.path.isdir(full_path) and self._normalize(name) == norm_slug:
                    match_folder = full_path
                    match_name = name
                    break

        display_name = match_name if match_name else guessed_name
        print(f"{'Comic':<{label_width}}: {display_name}")

        if not match_folder:
            print(f"{'Status':<{label_width}}: No previous download found.\n")
            return set()

        chapter_nums = self._get_completed_nums(match_folder)

        if not chapter_nums:
            print(f"{'Status':<{label_width}}: No previous download found.\n")
            return set()

        sorted_nums = sorted(chapter_nums)
        print(f"{'Downloaded':<{label_width}}: {len(sorted_nums)} Chapters")
        print(f"{'Last Downloaded':<{label_width}}: Chapter {sorted_nums[-1]:g}\n")
        return chapter_nums

    def _download_single_chapter(self, adapter, chap_url, dest_folder, driver,
                                  auto_cleanup=True, cancel_event=None):
        os.makedirs(dest_folder, exist_ok=True)

        try:
            valid_imgs = adapter.get_chapter_images(driver, chap_url, cancel_event=cancel_event)

            if cancel_event and cancel_event.is_set():
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0, "cancelled": True}

            if not valid_imgs:
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0, "error": "No images returned"}

            manifest = [{"page": idx, "url": src} for idx, src in enumerate(valid_imgs, 1)]
            try:
                with open(os.path.join(dest_folder, "chapter_manifest.json"), "w") as f:
                    json.dump(manifest, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            tasks = []
            for idx, src in enumerate(valid_imgs, 1):
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                path = os.path.join(dest_folder, f"{idx:03d}{ext}")
                tasks.append((src, path))

            stats = self.core.download_images(tasks)
            total = len(valid_imgs)

            if stats['ok'] > 0 and auto_cleanup and hasattr(adapter, "cleanup_chapter_folder"):
                try:
                    adapter.cleanup_chapter_folder(dest_folder)
                except Exception:
                    pass

            if stats['ok'] == 0:
                sample = tasks[0][0] if tasks else "N/A"
                return {"success": False, "pages": 0, "total": total, "size_mb": 0.0, "error": f"All image downloads failed. Sample URL: {sample}"}

            return {
                "success": True,
                "pages": stats['ok'],
                "total": total,
                "size_mb": stats['size'] / 1048576,
            }

        except Exception as e:
            return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0, "error": str(e)}

    def _download_gallery_item(self, adapter, gallery_url, driver):
        tmp_folder = tempfile.mkdtemp(prefix=f"gallery_")
        try:
            item_title = adapter.get_item_title(gallery_url)
            if not item_title:
                item_title = f"Gallery_{adapter.get_chapter_num(gallery_url)}"
            title_clean = self.core.clean_name(item_title)

            print(f"  Downloading: {title_clean}")

            result = self._download_single_chapter(
                adapter, gallery_url, tmp_folder, driver,
                auto_cleanup=True, cancel_event=self._cancel_event,
            )

            if self._cancel_event.is_set():
                self._cleanup_folder(tmp_folder)
                return None, 0.0

            if not result.get("success"):
                err_msg = result.get("error", "Unknown error")
                print(f"      [ERROR] {err_msg}")
                self._cleanup_folder(tmp_folder)
                return None, 0.0

            base_title = _extract_base_title(item_title)
            if not base_title:
                base_title = title_clean
            base_title_clean = self.core.clean_name(base_title)

            base_folder = os.path.join("Komik", base_title_clean)
            os.makedirs(base_folder, exist_ok=True)

            pdf_name = f"{title_clean}.pdf"
            pdf_path = os.path.join(base_folder, pdf_name)

            if os.path.isfile(pdf_path):
                print(f"      [SKIP] PDF already exists: {pdf_name}")
                self._cleanup_folder(tmp_folder)
                return None, 0.0

            ok = convert_chapter_to_pdf(tmp_folder, pdf_path)

            if ok and os.path.isfile(pdf_path):
                pdf_size = os.path.getsize(pdf_path) / 1048576
                dl_mb = result.get('size_mb', 0.0)
                print(f"  PDF saved : {base_title_clean}/{pdf_name} ({pdf_size:.1f} MB)")
                self._cleanup_folder(tmp_folder)
                tmp_folder = None
                return pdf_path, dl_mb
            else:
                print(f"  PDF failed: convert error")
                return None, 0.0
        finally:
            if tmp_folder and os.path.isdir(tmp_folder):
                self._cleanup_folder(tmp_folder)

    def run(self, url, start_ch=1, end_ch=9999,
            progress_callback=None, send_notifications=True,
            notify_on_error=True, base_dir="Komik", max_items=50):
        self._cancel_event.clear()
        self._unknown_counter = 0

        adapter = resolve_adapter(self.core, url)

        if getattr(adapter, 'PER_ITEM_SERIES', False):
            return self._run_gallery_search(adapter, url, max_items,
                                            send_notifications, notify_on_error)

        driver = self.core.get_driver(enable_images=False)
        try:
            title = adapter.get_title(driver, url)
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
            chapters = adapter.get_chapters(driver, url)
        finally:
            driver.quit()

        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        completed_nums = self._get_completed_nums(base_folder)
        to_download = []
        skipped = []

        for chap_url in chapters:
            num = adapter.get_chapter_num(chap_url)
            if num <= 0 or not (start_ch <= num <= end_ch):
                continue
            if num in completed_nums:
                skipped.append(num)
                continue
            to_download.append((num, chap_url))

        seen = set()
        deduped = []
        for num, chap_url in to_download:
            if num not in seen:
                seen.add(num)
                deduped.append((num, chap_url))
        to_download = sorted(deduped, key=lambda x: x[0])

        if skipped:
            preview = ", ".join(f"{n:g}" for n in sorted(skipped)[:10])
            more = f" (+{len(skipped) - 10} lainnya)" if len(skipped) > 10 else ""
            print(f"[INFO] Skip {len(skipped)} chapter sudah ada (PDF): {preview}{more}\n")

        if not to_download:
            print(f"[WARN] Tidak ada chapter baru dalam range {start_ch}-{end_ch}.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        total = len(to_download)
        print(f"\n[INFO] Akan mendownload + convert {total} chapter")
        print("-" * 50)

        if send_notifications:
            try:
                bot.start(title, start_ch, end_ch)
            except Exception:
                pass

        run_start = time.time()
        success_count = 0
        failed_count = 0
        cancelled_flag = False
        pdfs_created = []
        success_nums = []
        total_downloaded_mb = 0.0

        shared_driver = self.core.get_driver(enable_images=True)

        try:
            for idx, (num, chap_url) in enumerate(to_download, 1):
                if self._cancel_event.is_set():
                    print("[INFO] Dibatalkan oleh user.")
                    cancelled_flag = True
                    break

                label = f"{num:g}"
                print(f"\n  [{idx}/{total}] Chapter {label}")
                print(f"  {'-'*28}")

                tmp_folder = tempfile.mkdtemp(prefix=f"ch_{label}_")
                try:
                    result = self._download_single_chapter(
                        adapter, chap_url, tmp_folder, shared_driver,
                        auto_cleanup=True, cancel_event=self._cancel_event,
                    )
                except Exception as e:
                    print(f"      [ERROR] Download gagal: {e}")
                    if notify_on_error:
                        try:
                            bot.error(num, str(e))
                        except Exception:
                            pass
                    failed_count += 1
                    self._cleanup_folder(tmp_folder)
                    if progress_callback:
                        progress_callback(num, total, {"success": False, "pages": 0})
                    continue

                if result.get("cancelled"):
                    cancelled_flag = True
                    self._cleanup_folder(tmp_folder)
                    break

                if not result.get("success"):
                    print(f"      [WARN] Download gagal (0 gambar)")
                    failed_count += 1
                    self._cleanup_folder(tmp_folder)
                    if progress_callback:
                        progress_callback(num, total, result)
                    continue

                print(f"  Downloaded: {result['pages']} pages ({result['size_mb']:.1f} MB)")
                total_downloaded_mb += result['size_mb']

                chap_folder_name = os.path.basename(tmp_folder)
                proper_name = self.format_chapter_folder(num)
                proper_folder = os.path.join(base_folder, proper_name)

                if os.path.exists(proper_folder) and os.listdir(proper_folder):
                    proper_folder = tmp_folder
                else:
                    try:
                        if os.path.exists(proper_folder):
                            shutil.rmtree(proper_folder)
                        shutil.move(tmp_folder, proper_folder)
                        tmp_folder = None
                    except Exception as e:
                        print(f"      [WARN] Gagal rename folder: {e}")
                        proper_folder = tmp_folder

                chapter_label = get_chapter_label(proper_name)
                ok, pdf_path = self._convert_and_delete(proper_folder, result_dir, chapter_label)

                if ok:
                    success_count += 1
                    success_nums.append(num)
                    pdfs_created.append(pdf_path)
                    pdf_size = os.path.getsize(pdf_path) / 1048576
                    print(f"  PDF saved : Chapter_{label}.pdf ({pdf_size:.1f} MB)")
                else:
                    failed_count += 1
                    print(f"  PDF failed: convert error")

                if progress_callback:
                    progress_callback(num, total, result)

        finally:
            try:
                shared_driver.quit()
            except Exception:
                pass
            if tmp_folder and os.path.isdir(tmp_folder):
                self._cleanup_folder(tmp_folder)

        elapsed = time.time() - run_start
        mins, secs = divmod(int(elapsed), 60)
        durasi = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        total_size_mb = sum(os.path.getsize(p) / 1048576 for p in pdfs_created if os.path.isfile(p))

        downloaded_nums = sorted(success_nums)
        if downloaded_nums:
            first_ch = f"{downloaded_nums[0]:g}"
            last_ch = f"{downloaded_nums[-1]:g}"
            chapter_range = first_ch if first_ch == last_ch else f"{first_ch} - {last_ch}"
        else:
            chapter_range = "N/A"

        summary = {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "cancelled": cancelled_flag,
            "pdfs": pdfs_created,
        }

        print(f"\n{'='*50}")
        print(f"  DOWNLOAD COMPLETE")
        print(f"{'='*50}")
        print(f"  Title     : {title}")
        print(f"  Chapters  : {chapter_range} ({success_count} downloaded)")
        print(f"  Duration  : {durasi}")
        print(f"  Total     : {total} chapters")
        print(f"  Success   : {success_count}")
        print(f"  Failed    : {failed_count}")
        print(f"  Downloaded: {total_downloaded_mb:.1f} MB")
        print(f"  PDFs      : {len(pdfs_created)} files ({total_size_mb:.1f} MB)")
        print(f"  Location  : {result_dir}")
        print(f"{'='*50}\n")

        if send_notifications:
            try:
                bot.finish(title, success_count, total)
            except Exception:
                pass

        return summary

    def _run_gallery_search(self, adapter, url, max_items=50,
                            send_notifications=True, notify_on_error=True):
        print(f"[INFO] Mode     : Gallery Search")
        print(f"[INFO] Source   : {adapter.name}\n")

        driver = self.core.get_driver(enable_images=False)
        try:
            items = adapter.get_chapters(driver, url)
        finally:
            driver.quit()

        if not items:
            print("[ERROR] Tidak ada gallery ditemukan.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        items = items[:max_items]
        total_items = len(items)

        print(f"[INFO] Mendapatkan daftar gallery ({total_items})...")
        gallery_list = []
        for i, gallery_url in enumerate(items, 1):
            title = adapter.get_item_title(gallery_url)
            gallery_list.append((gallery_url, title))
            print(f"  [{i:3d}] {title or f'Gallery {adapter.get_chapter_num(gallery_url)}'}")

        print(f"\n[INFO] Total {total_items} gallery ditemukan.")
        range_input = input("Range yang mau di download (contoh: 1-5, 1,3,5, atau Enter untuk semua): ").strip()

        selected_indices = set()
        if not range_input:
            selected_indices = set(range(total_items))
        else:
            for part in range_input.split(','):
                part = part.strip()
                if '-' in part:
                    parts = part.split('-')
                    try:
                        start = int(parts[0]) - 1
                        end = int(parts[1]) if parts[1] else total_items
                        selected_indices.update(range(start, min(end, total_items)))
                    except ValueError:
                        pass
                else:
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < total_items:
                            selected_indices.add(idx)
                    except ValueError:
                        pass

        if not selected_indices:
            print("[WARN] Tidak ada gallery dipilih.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        selected = [(items[i], gallery_list[i][1]) for i in sorted(selected_indices)]
        total = len(selected)
        print(f"\n[INFO] Akan mendownload {total} gallery\n")

        run_start = time.time()
        success_count = 0
        failed_count = 0
        pdfs_created = []
        total_downloaded_mb = 0.0

        if send_notifications:
            try:
                bot.start(adapter.name, 1, total)
            except Exception:
                pass

        driver = self.core.get_driver(enable_images=True)
        try:
            for idx, (gallery_url, _) in enumerate(selected, 1):
                if self._cancel_event.is_set():
                    print("[INFO] Dibatalkan oleh user.")
                    break

                print(f"\n  [{idx}/{total}] Gallery")
                print(f"  {'-'*28}")

                pdf_path, dl_mb = self._download_gallery_item(adapter, gallery_url, driver)

                if self._cancel_event.is_set():
                    break
                if pdf_path:
                    success_count += 1
                    pdfs_created.append(pdf_path)
                    total_downloaded_mb += dl_mb
                else:
                    failed_count += 1

        finally:
            try:
                driver.quit()
            except Exception:
                pass

        elapsed = time.time() - run_start
        mins, secs = divmod(int(elapsed), 60)
        durasi = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        total_size_mb = sum(os.path.getsize(p) / 1048576 for p in pdfs_created if os.path.isfile(p))

        summary = {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "cancelled": self._cancel_event.is_set(),
            "pdfs": pdfs_created,
        }

        print(f"\n{'='*50}")
        print(f"  DOWNLOAD COMPLETE")
        print(f"{'='*50}")
        print(f"  Source    : {adapter.name}")
        print(f"  Total     : {total} gallery")
        print(f"  Success   : {success_count}")
        print(f"  Failed    : {failed_count}")
        print(f"  Duration  : {durasi}")
        print(f"  Downloaded: {total_downloaded_mb:.1f} MB")
        print(f"  PDFs      : {len(pdfs_created)} files ({total_size_mb:.1f} MB)")
        print(f"{'='*50}\n")

        if send_notifications:
            try:
                bot.finish(adapter.name, success_count, total)
            except Exception:
                pass

        return summary


if __name__ == "__main__":
    print("Omnivious Downloader - Multi-Site Comic/Manga/Doujin Downloader")
    print("Support: DemonicScans, Toonily, Comix, AsuraScans, Hentaifox, Cin.cx")
    print("-" * 60)

    url = input("Masukkan URL: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    dl = StreamingPDFDownloader()

    adapter_check = resolve_adapter(dl.core, url)
    is_gallery = getattr(adapter_check, 'PER_ITEM_SERIES', False)

    if is_gallery:
        result = dl.run(url, max_items=999999)
    else:
        completed = dl.detect_existing_progress(url)
        default_start = max(completed) + 1 if completed else 1

        start_input = input(f"Chapter mulai (default {default_start}): ").strip()
        end_input = input("Chapter akhir (default semua): ").strip()

        start = float(start_input) if start_input else default_start
        end = float(end_input) if end_input else 9999

        result = dl.run(url, start_ch=start, end_ch=end)
