from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from bs4 import BeautifulSoup, NavigableString
import requests
import io
import os
os.environ.setdefault('WDM_LOG', '0')
os.environ.setdefault('WDM_LOG_LEVEL', '0')
os.environ.setdefault('WDM_PRINT_FIRST_LINE', 'False')
import time
import re
import sys
import json
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from webdriver_manager.chrome import ChromeDriverManager
from notification_manager import TelegramNotifier
import convert as converter  # Disesuaikan dari comic_folder_to_pdf

# ============================================================
# NOTIFIKASI TELEGRAM (instance global dipakai di seluruh script)
# ============================================================
bot = TelegramNotifier()

# ------------------------------------------------------------
# Optional dependencies for the extra (best-effort) validation
# layers used inside GenericSiteAdapter (image hashing, OCR).
# None of these are hard requirements -- if a library is missing
# the related layer is silently skipped and the adapter falls
# back to the DOM/URL/aspect-ratio checks only.
# ------------------------------------------------------------
try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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

JUNK_SIGNATURES_FILE = "junk_signatures.json"

_junk_signatures_lock = Lock()


def _load_junk_signatures(path=JUNK_SIGNATURES_FILE):
    """Load the small, self-learning store of trailing-junk signatures
    (URL keywords + perceptual image hashes) that cleanup_chapter_folder()
    has previously identified. Used by GenericSiteAdapter to reject the
    same junk earlier next time, before it's even downloaded. Missing or
    corrupt files are treated as empty -- this is a best-effort cache,
    never a hard dependency."""
    with _junk_signatures_lock:
        if not os.path.exists(path):
            return {"keywords": [], "hashes": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "keywords": list(data.get("keywords", [])),
                "hashes": list(data.get("hashes", [])),
            }
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


def list_downloaded_comics(base_dir="Komik"):
    """Fungsi helper yang dibutuhkan oleh telegram_bot_listener.py"""
    if not os.path.exists(base_dir):
        return []
    return [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]


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

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max_workers,
            pool_maxsize=max_workers * 2,
            max_retries=2,
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
# SITE ADAPTERS
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

    def get_chapter_images(self, driver, chap_url, cancel_event=None):
        raise NotImplementedError


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

    # Text-based end markers -- checked against the *visible text* of nodes
    # encountered while walking the reader container in document order.
    # A match means "stop extraction here", not "skip this node".
    TEXT_END_MARKERS = (
        'end chapter', 'end of chapter', 'the end', 'thanks for reading',
        'thank you for reading', 'read next', 'recommendation',
        'recommended for you', 'you may also like', 'you might also like',
        'join discord', 'join our discord', 'support us',
        'support the author', 'buy me a coffee', 'leave a comment',
        'comments (', 'next chapter', 'previous chapter',
    )

    VALID_IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')

    # Minimum height/width ratio to still be considered a "portrait" comic
    # page. Manga/manhwa/manhua pages are essentially always taller than
    # wide; banners, dividers and promo cards are usually landscape/square.
    MIN_PORTRAIT_RATIO = 0.9

    # --- DIGABUNGKAN DARI VERSI AWAL ADAPTER -----------------------------
    # Pola URL yang menjadi "sinyal kuat" bahwa sebuah <img> memang gambar
    # halaman chapter: berada di dalam folder/segmen path seperti
    # /chapters/, /chapter/, /pages/, /page/, dan berekstensi gambar umum.
    # Banyak situs komik memang menaruh file halaman persis di path ini,
    # jadi kalau URL cocok, kita bisa langsung percaya tanpa perlu lolos
    # semua pengecekan tambahan di bawah (lihat _is_valid_page_image).
    CHAPTER_IMAGE_PATTERNS = re.compile(
        r'/(chapters|chapter|pages?)/.*?\.(webp|jpg|jpeg|png)', re.IGNORECASE
    )
    # ----------------------------------------------------------------------

    READER_SELECTORS = (
        "div#readerarea, div.reading-content, div.reader-area, "
        "div.chapter-content, section#chapter, div.chapter-images, "
        "div.container-chapter-reader, div.page-break, "
        "div[class*='reader'], div[id*='reader'], main"
    )

    # Non-reader sections removed from the DOM *before* any image is
    # extracted. Kept broad (class/id substring matches) on purpose, since
    # sites don't share a common markup vocabulary -- this must stay
    # universal, not tailored to one site's class names.
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
            # Cek Stop DI DALAM loop scroll, bukan cuma di antar-chapter --
            # loop ini bisa memakan sampai puluhan detik (60 x 0.8s), dan
            # sebelumnya cancel_event sama sekali tidak dicek di sini,
            # sehingga tombol Stop terasa "macet" selama chapter yang
            # sedang di-scroll belum selesai.
            if cancel_event and cancel_event.is_set():
                break
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
            # Berhenti total di sini -- jangan lanjut ke scroll-to-top,
            # cleanup script, sleep tambahan, atau parsing HTML sama sekali,
            # karena hasilnya toh tidak akan dipakai (job sedang dibatalkan).
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
                    // Stamp the browser-computed natural dimensions onto the
                    // element so the aspect-ratio validation layer can read
                    // them later from the static HTML (page_source), without
                    // needing another round-trip to the browser.
                    if (img.naturalWidth) img.setAttribute('data-natural-width', img.naturalWidth);
                    if (img.naturalHeight) img.setAttribute('data-natural-height', img.naturalHeight);
                }
            });
        """)
        time.sleep(2.5)

        if cancel_event and cancel_event.is_set():
            return []

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Strip non-reader sections (header/footer/comments/sidebar/
        # recommendation/related/navigation/ads/social/support/discord)
        # BEFORE any image is looked at, so junk never enters the candidate
        # pool in the first place.
        for tag in soup.select(self.EXCLUDE_SECTION_SELECTORS):
            tag.decompose()

        reader_container = soup.select_one(self.READER_SELECTORS) or soup

        candidates = self._extract_sequential_images(reader_container, chap_url)
        candidates = self._dedupe_keep_order(candidates)
        candidates = self._filter_domain_outliers(candidates)

        return candidates

    def _extract_sequential_images(self, reader_container, base_url):
        """
        Single ordered pass over the reader container (document order, not
        a flat find_all('img') over the whole page). For every node it
        either:
          - collects a validated chapter-page image, or
          - skips a node that doesn't look like real content yet (e.g. a
            leading logo before any real page was found), or
          - STOPS extraction entirely once a genuine end-of-chapter marker
            is found (DOM/text marker, URL marker, or a piece of junk
            appearing right after real pages) -- it never keeps scanning
            past that point, per the "stop, don't just skip" requirement.
        """
        urls = []
        valid_count = 0

        for node in reader_container.descendants:
            # --- Text-based DOM marker: unconditional stop -----------------
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

            # --- URL-based end marker: unconditional stop -------------------
            if any(marker in low for marker in self.END_MARKERS):
                break

            # --- Keyword validation (banner/logo/avatar/emoji/icon/
            #     thumbnail/cover/promo/footer/recommendation/etc.) --------
            if not self._is_valid_page_image(url):
                if valid_count > 0:
                    # Junk appearing right after real chapter pages -- this
                    # is the "sequential detection" signal: STOP here rather
                    # than silently skipping and continuing to scan.
                    break
                # Junk appearing before any real page (e.g. a masthead
                # logo) -- just skip it and keep looking.
                continue

            # --- Aspect-ratio validation (portrait pages only) --------------
            width = self._to_float(img.get('data-natural-width'))
            height = self._to_float(img.get('data-natural-height'))
            if width and height and width > 0:
                ratio = height / width
                if ratio < self.MIN_PORTRAIT_RATIO:
                    if valid_count > 0:
                        break
                    continue

            # --- Learned junk signatures (from cleanup_chapter_folder) -----
            if self._matches_known_junk_keyword(url):
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
        """Cheap, dependency-free check against keywords learned by
        cleanup_chapter_folder() on previous runs (e.g. a site-specific
        promo filename pattern that isn't covered by BLOCKED_KEYWORDS)."""
        keywords = _load_junk_signatures().get("keywords", [])
        if not keywords:
            return False
        low = url.lower()
        return any(kw in low for kw in keywords)

    def _is_valid_page_image(self, url):
        low = url.lower()
        path = urllib.parse.urlparse(low).path
        basename = os.path.basename(path)

        # 1) Blocklist keyword pada nama file (logo/cover/ads/dll) --
        #    ini tetap jalan lebih dulu, apapun bentuk path-nya, supaya
        #    file yang jelas-jelas junk tidak pernah lolos hanya karena
        #    kebetulan berada di folder /chapter/.
        for kw in self.BLOCKED_KEYWORDS:
            if re.search(rf'(?:^|[^a-z0-9]){re.escape(kw)}(?:[^a-z0-9]|$)', basename):
                return False

        # 2) SINYAL KUAT dari versi awal adapter: kalau path URL persis
        #    mengandung folder /chapters/, /chapter/, /pages/, atau /page/
        #    dan diakhiri ekstensi gambar umum, ini nyaris pasti gambar
        #    halaman komik yang sah. Begitu cocok, langsung anggap valid
        #    tanpa perlu lolos aturan ekstensi/fallback di bawah -- ini
        #    membuat deteksi lebih cepat & lebih presisi untuk situs yang
        #    memang menaruh gambar chapter di path semacam itu.
        if self.CHAPTER_IMAGE_PATTERNS.search(low):
            return True

        # 3) Fallback lama (untuk situs yang TIDAK pakai konvensi
        #    /chapter//pages/ pada path gambarnya -- misalnya CDN yang
        #    hanya menaruh file di /uploads/<judul>/001.jpg tanpa kata
        #    "chapter" sama sekali). Ini yang menjaga kompatibilitas luas
        #    generic adapter supaya tidak menolak situs yang polanya beda.
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

    # ------------------------------------------------------------
    # Post-download cleanup (universal, not tied to any one site).
    #
    # get_chapter_images() already stops at the first DOM/URL/aspect-ratio
    # marker it recognizes, but a brand-new site may use a closing banner
    # that slips past every filter once (e.g. an image with no matching
    # keyword and a portrait-ish crop). cleanup_chapter_folder() is the
    # safety net: it runs AFTER the files are already on disk, looks at the
    # tail of the chapter for anything that doesn't belong, deletes it and
    # everything after it, renumbers what's left, and remembers the junk's
    # signature so get_chapter_images() can reject it pre-emptively next
    # time (via junk_signatures.json).
    #
    # NOTE: this method is intentionally self-contained. Wiring it in is a
    # single call -- e.g. `adapter.cleanup_chapter_folder(folder)` -- right
    # after a chapter's files finish downloading.
    # ------------------------------------------------------------
    def cleanup_chapter_folder(self, folder, tail_check=5):
        """
        Scan the last `tail_check` images (in filename order) of an already
        -downloaded chapter folder for trailing junk (Discord/recommendation/
        promo/footer/next-chapter/etc. banners) that made it past the
        scan-time filters. If junk is found at position i, that file and
        every file after it are deleted, the remaining files are renumbered
        sequentially (001, 002, ...), chapter_manifest.json is trimmed to
        match, and the junk's signature (filename keyword + perceptual hash
        if available) is recorded in junk_signatures.json for future runs.

        Returns the number of files removed.
        """
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
        """Returns (is_junk: bool, keyword_signature: str|None, phash: str|None)."""
        filename = os.path.basename(filepath).lower()

        # Layer 1: filename/URL-style keyword check (same keyword list used
        # at scan time, in case the original URL keyword survived into the
        # saved filename).
        for kw in self.BLOCKED_KEYWORDS + self.END_MARKERS:
            if kw in filename:
                return True, kw, None

        if not _PIL_AVAILABLE:
            return False, None, None

        try:
            with Image.open(filepath) as img:
                width, height = img.size

                # Layer 2: aspect ratio -- trailing junk is usually
                # landscape/square, real pages are portrait.
                is_landscape_ish = width > 0 and (height / width) < self.MIN_PORTRAIT_RATIO

                phash = None
                if _IMAGEHASH_AVAILABLE:
                    try:
                        phash = str(imagehash.phash(img))
                    except Exception:
                        phash = None

                # Layer 3: perceptual hash against previously learned junk.
                if phash and phash in known_hashes:
                    return True, None, phash

                if is_landscape_ish:
                    # Layer 4 (best-effort): OCR the suspect image for
                    # closing-card text before condemning it, since some
                    # portrait promo cards are still tall/narrow.
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
        self._unknown_counter = 0

    def format_chapter_folder(self, chap_num):
        if chap_num is None or chap_num <= 0:
            self._unknown_counter += 1
            return f"Chapter_Unknown_{self._unknown_counter}"
        if float(chap_num).is_integer():
            return f"{int(chap_num):04d}"
        integer_part, _, decimal_part = f"{chap_num:g}".partition('.')
        return f"{int(integer_part):04d}.{decimal_part}"

    @staticmethod
    def write_chapter_manifest(folder, valid_imgs):
        manifest = [
            {"page": idx, "url": src}
            for idx, src in enumerate(valid_imgs, 1)
        ]
        manifest_path = os.path.join(folder, "chapter_manifest.json")
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"      [!] Gagal menulis chapter_manifest.json: {e}")

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

    @staticmethod
    def get_completed_chapter_numbers(base_folder):
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

    def detect_existing_progress(self, series_url, komik_root="Komik"):
        label_width = 17
        slug = self._extract_slug(series_url)
        norm_slug = self._normalize(slug)
        guessed_name = self._guess_display_name(slug) or slug

        match_folder = None
        match_name = None
        if os.path.isdir(komik_root):
            for name in os.listdir(komik_root):
                full_path = os.path.join(komik_root, name)
                if os.path.isdir(full_path) and self._normalize(name) == norm_slug:
                    match_folder = full_path
                    match_name = name
                    break

        display_name = match_name if match_name else guessed_name
        print(f"{'Comic':<{label_width}}: {display_name}")

        if not match_folder:
            print("No previous download found.\n")
            return set()

        chapter_nums = self.get_completed_chapter_numbers(match_folder)

        if not chapter_nums:
            print("No previous download found.\n")
            return set()

        sorted_nums = sorted(chapter_nums)
        print(f"{'Downloaded':<{label_width}}: {len(sorted_nums)} Chapters")
        print(f"{'Last Downloaded':<{label_width}}: Chapter {sorted_nums[-1]:g}\n")
        return chapter_nums

    def download_chapter(self, adapter, chap_url, base_folder, driver=None, auto_cleanup=True, cancel_event=None):
        own_driver = driver is None
        chap_num = adapter.get_chapter_num(chap_url)
        folder_name = self.format_chapter_folder(chap_num)
        folder = os.path.join(base_folder, folder_name)
        os.makedirs(folder, exist_ok=True)

        try:
            if own_driver:
                driver = self.core.get_driver(enable_images=True)

            valid_imgs = adapter.get_chapter_images(driver, chap_url, cancel_event=cancel_event)

            # Stop dipencet SAAT proses scraping halaman (di dalam loop
            # scroll get_chapter_images) -- jangan lanjut download gambar
            # sama sekali. Chapter ini dianggap belum selesai/dibatalkan,
            # bukan "gagal", supaya tidak dihitung sebagai Failed dan tidak
            # memicu notifikasi error yang salah kaprah.
            if cancel_event and cancel_event.is_set():
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0, "cancelled": True}

            if not valid_imgs:
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}

            self.write_chapter_manifest(folder, valid_imgs)

            tasks = []
            for idx, src in enumerate(valid_imgs, 1):
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                path = os.path.join(folder, f"{idx:03d}{ext}")
                tasks.append((src, path))

            stats = self.core.download_images(tasks)
            total = len(valid_imgs)
            success = stats['ok'] > 0

            # Safety net dari versi awal adapter: setelah download selesai,
            # bersihkan kemungkinan gambar penutup/promosi yang lolos dari
            # filter saat scanning (lihat cleanup_chapter_folder()). Hanya
            # dijalankan kalau setting "Auto Cleanup" ON (auto_cleanup=True) --
            # sebelumnya ini selalu jalan tanpa syarat sehingga toggle di
            # menu Settings tidak berpengaruh apa pun.
            if success and auto_cleanup and hasattr(adapter, "cleanup_chapter_folder"):
                try:
                    adapter.cleanup_chapter_folder(folder)
                except Exception:
                    pass

            return {
                "success": success,
                "pages": stats['ok'],
                "total": total,
                "size_mb": stats['size'] / 1048576,
            }
        except Exception:
            return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}
        finally:
            if own_driver and driver:
                driver.quit()

    def run(self, series_url, start_ch=1, end_ch=9999, completed_nums=None,
            progress_callback=None, send_notifications=True, notify_on_error=True,
            cancel_event=None, base_dir="Komik", auto_cleanup=True, driver_holder=None):
        """
        base_dir        : folder root tempat komik disimpan (dulu hardcode "Komik").
        auto_cleanup    : diteruskan ke download_chapter() -- kalau False, gambar
                          penutup/promosi yang lolos filter TIDAK dibersihkan
                          otomatis setelah chapter selesai didownload.
        send_notifications : gerbang notifikasi Telegram START & FINISH
                          (bot.start / bot.finish). Sebelumnya satu flag ini
                          juga menggerbang notifikasi ERROR per-chapter,
                          sehingga toggle "Error Notification" di menu
                          Settings tidak berpengaruh apa pun kalau
                          "Download Finished" notif di-OFF-kan. Sekarang
                          error notif punya flag sendiri (notify_on_error).
        notify_on_error : gerbang notifikasi Telegram ERROR per-chapter
                          (bot.error), TERPISAH dari send_notifications --
                          diisi dari settings["notify_error"] di listener.
        driver_holder  : dict opsional (mis. {}) yang akan diisi
                         {'driver': <selenium webdriver aktif>} selama proses
                         berjalan. Dipakai oleh pemanggil (listener) supaya
                         tombol Stop bisa memanggil driver.quit() langsung dari
                         thread lain -- ini yang membuat Stop benar-benar
                         memutus proses yang sedang berjalan (bukan cuma
                         berhenti setelah chapter aktif selesai).
        cancel_event   : threading.Event opsional. Selain dicek di antara
                         chapter, sekarang juga diteruskan ke
                         adapter.get_chapter_images() sehingga dicek di
                         DALAM loop scroll per-chapter -- ini yang membuat
                         Stop benar-benar responsif walau sedang di tengah
                         satu chapter, bukan menunggu chapter itu selesai.
        """
        completed_nums = completed_nums or set()

        adapter = resolve_adapter(self.core, series_url)

        driver = self.core.get_driver(enable_images=False)
        try:
            title = adapter.get_title(driver, series_url)
        finally:
            driver.quit()

        base_folder = os.path.join(base_dir, title)
        os.makedirs(base_folder, exist_ok=True)
        print(f"[INFO] Judul  : {title}")
        print(f"[INFO] Folder : {base_folder}\n")

        driver = self.core.get_driver(enable_images=False)
        try:
            chapters = adapter.get_chapters(driver, series_url)
        finally:
            driver.quit()

        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan. Coba cek URL, atau situs butuh adapter khusus baru.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False}

        completed_nums = completed_nums | self.get_completed_chapter_numbers(base_folder)

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
            if num in seen:
                continue
            seen.add(num)
            deduped.append((num, url))
        to_download = sorted(deduped, key=lambda x: x[0])

        if skipped_nums:
            preview = ", ".join(f"{n:g}" for n in sorted(skipped_nums)[:10])
            more = f" (+{len(skipped_nums) - 10} lagi)" if len(skipped_nums) > 10 else ""
            print(f"[INFO] Melewati {len(skipped_nums)} chapter yang sudah ada (folder/PDF): {preview}{more}\n")

        if not to_download:
            print(f"[WARN] Tidak ada chapter baru untuk didownload dalam range {start_ch}-{end_ch}.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False}

        print(f"[INFO] Akan mendownload {len(to_download)} chapter (range {start_ch}-{end_ch})\n")

        run_start_time = time.time()

        if send_notifications:
            try:
                bot.start(title, start_ch, end_ch)
            except Exception as e:
                print(f"   [!] Gagal mengirim notifikasi Telegram (start): {e}")

        success_count = 0
        failed_count = 0
        cancelled_flag = False

        shared_driver = self.core.get_driver(enable_images=True)
        if driver_holder is not None:
            driver_holder['driver'] = shared_driver

        try:
            for idx, (num, url) in enumerate(to_download, 1):
                if cancel_event and cancel_event.is_set():
                    print("[INFO] Proses dibatalkan oleh perintah sistem.")
                    cancelled_flag = True
                    break

                label = f"{num:g}"
                print(f"[{idx}/{len(to_download)}] Chapter {label}")

                try:
                    result = self.download_chapter(adapter, url, base_folder, driver=shared_driver, auto_cleanup=auto_cleanup, cancel_event=cancel_event)
                except WebDriverException as e:
                    # Kalau browser mati karena tombol Stop dipencet (job_stop
                    # memanggil driver.quit() langsung dari thread lain), JANGAN
                    # bikin browser baru dan lanjut mendownload -- itu justru
                    # membuat Stop terasa tidak berfungsi. Cukup hentikan total.
                    if cancel_event and cancel_event.is_set():
                        print("[INFO] Browser dihentikan oleh user (Stop). Proses dibatalkan.")
                        cancelled_flag = True
                        break

                    print(f"   [!] Browser bermasalah ({e.__class__.__name__}), membuat ulang session...")
                    if notify_on_error:
                        try:
                            bot.error(num, str(e))
                        except Exception as notif_err:
                            pass
                    try:
                        shared_driver.quit()
                    except Exception:
                        pass
                    shared_driver = self.core.get_driver(enable_images=True)
                    if driver_holder is not None:
                        driver_holder['driver'] = shared_driver
                    try:
                        result = self.download_chapter(adapter, url, base_folder, driver=shared_driver, auto_cleanup=auto_cleanup, cancel_event=cancel_event)
                    except Exception as e2:
                        print(f"   [!] Chapter {label} gagal total setelah re-create browser: {e2}")
                        if notify_on_error:
                            try:
                                bot.error(num, str(e2))
                            except Exception as notif_err:
                                pass
                        result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}

                if cancel_event and cancel_event.is_set():
                    # Ditangkap sedini mungkin, sebelum masuk ke logika retry
                    # di bawah -- result bisa saja "cancelled": True (Stop
                    # kena di tengah scroll) atau browser sudah mati duluan.
                    # Baik satu-satunya yang penting: JANGAN retry, JANGAN
                    # hitung sebagai Failed.
                    print("[INFO] Proses dibatalkan oleh perintah sistem.")
                    cancelled_flag = True
                    break

                if not result["success"]:
                    print("   [retry] Percobaan ulang 1x...")
                    time.sleep(2)
                    try:
                        result = self.download_chapter(adapter, url, base_folder, driver=shared_driver, auto_cleanup=auto_cleanup, cancel_event=cancel_event)
                    except WebDriverException as e:
                        if cancel_event and cancel_event.is_set():
                            print("[INFO] Browser dihentikan oleh user (Stop). Proses dibatalkan.")
                            cancelled_flag = True
                            break
                        print(f"   [!] Retry chapter {label} gagal: {e}")
                        if notify_on_error:
                            try:
                                bot.error(num, str(e))
                            except Exception as notif_err:
                                pass
                        result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}
                    except Exception as e:
                        print(f"   [!] Retry chapter {label} gagal: {e}")
                        if notify_on_error:
                            try:
                                bot.error(num, str(e))
                            except Exception as notif_err:
                                pass
                        result = {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}

                if cancel_event and cancel_event.is_set():
                    cancelled_flag = True
                    break

                if result["success"]:
                    if result["pages"] < result["total"]:
                        missing = result["total"] - result["pages"]
                        print(f"✓ Downloaded ({result['pages']}/{result['total']} pages, "
                              f"{result['size_mb']:.1f} MB) -- {missing} gambar gagal walau sudah di-retry\n")
                    else:
                        print(f"✓ Downloaded ({result['pages']} pages, {result['size_mb']:.1f} MB)\n")
                    success_count += 1
                else:
                    print("✗ Failed\n")
                    if notify_on_error:
                        try:
                            bot.error(num, "Gagal mendownload chapter (0 halaman berhasil setelah retry)")
                        except Exception as notif_err:
                            pass
                    failed_count += 1

                if progress_callback:
                    progress_callback(idx, len(to_download), num, {"success": result["success"], "error": "Failed" if not result["success"] else None})

                time.sleep(2)
        finally:
            try:
                shared_driver.quit()
            except Exception:
                pass
            if driver_holder is not None:
                driver_holder.clear()

        print("Finished")
        print(f"Success: {success_count}")
        print(f"Failed : {failed_count}")
        if skipped_nums:
            print(f"Skipped: {len(skipped_nums)} (sudah ada sebelumnya)")

        elapsed_seconds = time.time() - run_start_time
        h, rem = divmod(int(elapsed_seconds), 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            durasi = f"{h}h {m}m {s}s"
        elif m > 0:
            durasi = f"{m}m {s}s"
        else:
            durasi = f"{s}s"

        if send_notifications and not cancelled_flag:
            try:
                bot.finish(title, len(to_download), success_count, failed_count, durasi)
            except Exception as e:
                print(f"   [!] Gagal mengirim notifikasi Telegram (finish): {e}")

        return {
            "total": len(to_download),
            "success": success_count,
            "failed": failed_count,
            "cancelled": cancelled_flag
        }


if __name__ == "__main__":
    print("Universal Comic Downloader")
    print("Mendukung situs apapun (mode generic), plus adapter khusus untuk: "
          + ", ".join(SITE_ADAPTERS.keys()))
    print("-" * 50)

    url = input("Masukkan URL series: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    downloader = UniversalComicDownloader()

    completed_nums = downloader.detect_existing_progress(url)

    start_input = input("Chapter mulai (default 1): ").strip()
    end_input = input("Chapter akhir (default semua): ").strip()

    start = float(start_input) if start_input else 1
    end = float(end_input) if end_input else 9999

    downloader.run(url, start, end, completed_nums=completed_nums)