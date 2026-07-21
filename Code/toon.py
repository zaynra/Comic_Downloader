from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from PIL import Image
import requests
import os
import time
import urllib.parse
import re
from pathlib import Path
from webdriver_manager.chrome import ChromeDriverManager
import logging
import concurrent.futures
from threading import Lock
import base64

# Setup minimal logging untuk kode
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

# Suppress semua log dependensi
for logger_name in ['WDM', 'selenium', 'urllib3', 'tensorflow', 'absl']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# Nonaktifkan log TensorFlow
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

class ToonilyComicDownloader:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        }
        self.max_workers = 4
        self.download_lock = Lock()
        self.stats = {'downloaded': 0, 'failed': 0, 'total_size': 0}
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
    def setup_driver(self, enable_images=True):
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--window-size=1920,6000")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--allow-insecure-localhost")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument("--silent")
            
            image_setting = 1 if enable_images else 2
            prefs = {
                "profile.managed_default_content_settings.images": image_setting,
                "profile.default_content_setting_values.notifications": 2
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            service.log_path = os.devnull
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": self.headers['User-Agent']})
            driver.set_page_load_timeout(60)
            return driver
        except Exception as e:
            print(f"❌ Error setting up driver: {e}")
            return None
    
    def handle_age_verification(self, driver):
        try:
            # Handle modal popups
            modal_selectors = ["#adult_modal", ".modal", ".modal-content", "body.modal-open .modal"]
            for selector in modal_selectors:
                modal = driver.find_elements(By.CSS_SELECTOR, selector)
                if modal and modal[0].is_displayed():
                    age_buttons = [
                        "#adult_modal .modal-footer .btn.btn-primary",
                        ".modal .btn-primary",
                        ".modal button:contains('18+')",
                        ".modal button:contains('Yes')",
                        ".modal button:contains('Enter')"
                    ]
                    for btn_selector in age_buttons:
                        try:
                            if ':contains' in btn_selector:
                                js_selector = btn_selector.split(':contains')[0]
                                elements = driver.execute_script(f"""
                                    return Array.from(document.querySelectorAll('{js_selector}')).filter(
                                        el => el.textContent.includes('18+') || 
                                              el.textContent.includes('Yes') || 
                                              el.textContent.includes('Enter') ||
                                              el.textContent.includes('Continue')
                                    );
                                """)
                                if elements:
                                    driver.execute_script("arguments[0].click();", elements[0])
                                    time.sleep(3)
                                    break
                            else:
                                element = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, btn_selector))
                                )
                                driver.execute_script("arguments[0].click();", element)
                                time.sleep(3)
                                break
                        except:
                            continue
                    break
            
            # Force Family Mode off via JavaScript
            driver.execute_script("""
                var sections = document.querySelectorAll('.section_adult.on');
                sections.forEach(function(section) {
                    section.classList.remove('on');
                    section.classList.add('off');
                });
                var overlays = document.querySelectorAll('.age-gate, .age-verification, .overlay, #adult_modal, .modal');
                overlays.forEach(function(overlay) {
                    overlay.style.display = 'none';
                });
                document.body.classList.remove('modal-open');
            """)
            time.sleep(1)
            return True
        except Exception as e:
            print(f"❌ Error handling age verification: {e}")
            return False
    
    def clean_filename(self, filename):
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = re.sub(r'\s+', ' ', filename).strip()
        return filename[:100]
        
    def get_comic_title(self, series_url):
        try:
            driver = self.setup_driver(enable_images=False)
            if not driver:
                return "Unknown_Comic"
            driver.get("https://toonily.com/")
            self.handle_age_verification(driver)
            driver.get(series_url)
            self.handle_age_verification(driver)
            
            title_selectors = [
                'h1.entry-title', 'body.manga-page .profile-manga .post-title h1',
                'body.manga-page .profile-manga .post-title', 'h1.wp-block-heading',
                'h1', '.entry-title', '.post-title', '.series-title'
            ]
            
            title = None
            for selector in title_selectors:
                try:
                    title_element = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    title = title_element.text.strip()
                    if title and len(title) > 2:
                        break
                except:
                    continue
            
            driver.quit()
            if not title:
                title = series_url.split('/')[-1].replace('-', ' ').title()
            title = self.clean_filename(title)
            print(f"📚 Comic: {title}")
            return title
        except Exception as e:
            print(f"❌ Error getting comic title: {e}")
            return "Unknown_Comic"
    
    def get_chapter_links(self, series_url):
        try:
            driver = self.setup_driver(enable_images=False)
            if not driver:
                return []
            
            print("🔍 Scanning chapters...")
            driver.get("https://toonily.com/")
            self.handle_age_verification(driver)
            driver.get(series_url)
            self.handle_age_verification(driver)
            time.sleep(3)
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            no_change_count = 0
            max_no_change = 3
            while no_change_count < max_no_change:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    no_change_count += 1
                else:
                    no_change_count = 0
                last_height = new_height
            
            html = driver.page_source
            driver.quit()
            
            soup = BeautifulSoup(html, 'html.parser')
            chapter_links = []
            
            chapter_selectors = [
                'body.manga-page .page-content-listing.single-page .listing-chapters_wrap ul.main li a',
                'body.manga-page .page-content-listing.single-page .listing-chapters_wrap ul.main.version-chap li a',
                '.listing-chapters_wrap ul.main.version-chap .wp-manga-chapter a',
                '.listing-chapters_wrap ul.main li a', 'a[href*="/chapter-"]',
                'a[href*="/chapter/"]', '.wp-manga-chapter a', '.chapter-link',
                'a[title*="Chapter"]', 'ul.main li a', '.chapter-list a'
            ]
            
            for selector in chapter_selectors:
                try:
                    links = soup.select(selector)
                    if links:
                        for link in links:
                            href = link.get('href', '')
                            if href and ('/chapter-' in href or '/chapter/' in href or '/ch-' in href):
                                full_url = urllib.parse.urljoin(series_url, href)
                                chapter_links.append(full_url)
                        if chapter_links:
                            break
                except:
                    continue
            
            chapter_links = list(set(chapter_links))
            
            def extract_chapter_num(url):
                patterns = [r'/chapter-(\d+(?:\.\d+)?)', r'/chapter/(\d+(?:\.\d+)?)', r'/ch-(\d+(?:\.\d+)?)']
                for pattern in patterns:
                    match = re.search(pattern, url)
                    if match:
                        return float(match.group(1))
                return 0
            
            chapter_links.sort(key=extract_chapter_num)
            if chapter_links:
                print(f"📋 Found {len(chapter_links)} chapters (Chapter {extract_chapter_num(chapter_links[0])} to {extract_chapter_num(chapter_links[-1])})")
            return chapter_links
        except Exception as e:
            print(f"❌ Error getting chapter links: {e}")
            return []
    
    def download_single_image(self, img_data):
        img_src, filepath, chapter_url = img_data
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if img_src.startswith("data:image"):
                    base64_data = re.sub(r'^data:image/[^;]+;base64,', '', img_src)
                    img_data_decoded = base64.b64decode(base64_data)
                    with open(filepath, 'wb') as f:
                        f.write(img_data_decoded)
                else:
                    headers = self.headers.copy()
                    headers['Referer'] = chapter_url
                    headers['Accept'] = 'image/webp,image/apng,image/*,*/*;q=0.8'
                    response = self.session.get(img_src, headers=headers, stream=True, timeout=30)
                    response.raise_for_status()
                    content_type = response.headers.get('content-type', '').lower()
                    if not any(img_type in content_type for img_type in ['image/', 'application/octet-stream']):
                        raise Exception(f"Invalid content type: {content_type}")
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                
                if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
                    file_size = os.path.getsize(filepath)
                    with self.download_lock:
                        self.stats['downloaded'] += 1
                        self.stats['total_size'] += file_size
                    return True
                else:
                    raise Exception("Downloaded file is empty or too small")
            except Exception as e:
                if attempt == max_retries - 1:
                    with self.download_lock:
                        self.stats['failed'] += 1
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except:
                        pass
                else:
                    time.sleep(2)
        return False
    
    def natural_sort_key(self, filename):
        """
        Extract number dari filename untuk sorting numerik yang benar.
        Contoh: "page_009.jpg" -> 9, "page_010.jpg" -> 10
        """
        s = str(filename)
        # Cari nomor halaman (page_XXX)
        m = re.search(r'page[_-]?(\d+)', s, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Cari angka apapun di filename
        numbers = re.findall(r'\d+', s)
        if numbers:
            return int(numbers[-1])
        return 0
    
    def create_pdf_from_chapter(self, chapter_folder, comic_title, chapter_num):
        """
        Konversi folder chapter menjadi PDF dengan urutan halaman yang benar.
        """
        try:
            print(f"📄 Converting Chapter {chapter_num} to PDF...")
            
            # Ambil semua file gambar
            image_files = []
            for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp']:
                image_files.extend(Path(chapter_folder).glob(ext))
            
            if not image_files:
                print(f"⚠️ No images found in {chapter_folder}")
                return None
            
            # Sorting NUMERIK (bukan alfabetik) berdasarkan nomor halaman
            image_files.sort(key=self.natural_sort_key)
            
            # Debug: tampilkan urutan
            print(f"   Page order: {[f.name for f in image_files[:3]]} ... {[f.name for f in image_files[-3:]]} (total: {len(image_files)})")
            
            # Buka dan proses gambar
            images = []
            for img_path in image_files:
                try:
                    img = Image.open(img_path)
                    
                    # Konversi ke RGB untuk PDF
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode in ('RGBA', 'LA'):
                            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                            img = background
                        else:
                            img = img.convert('RGB')
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    images.append(img)
                except Exception as e:
                    print(f"   ⚠️ Error processing {img_path.name}: {e}")
                    continue
            
            if not images:
                print(f"❌ No valid images to convert for Chapter {chapter_num}")
                return None
            
            # Buat nama file PDF
            pdf_filename = f"{comic_title}_Chapter_{chapter_num.replace('.', '_').zfill(3)}.pdf"
            pdf_path = os.path.join(os.path.dirname(chapter_folder), pdf_filename)
            
            # Simpan PDF
            first_image = images[0]
            rest_images = images[1:] if len(images) > 1 else []
            
            first_image.save(
                pdf_path,
                save_all=True,
                append_images=rest_images,
                resolution=100.0
            )
            
            # Tutup semua gambar untuk free memory
            for img in images:
                img.close()
            
            # Info ukuran file
            file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            print(f"✅ PDF created: {pdf_filename} ({file_size_mb:.1f}MB, {len(image_files)} pages)")
            
            return pdf_path
            
        except Exception as e:
            print(f"❌ Error creating PDF for Chapter {chapter_num}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def download_chapter_images(self, chapter_url, comic_folder, comic_title):
        """
        Download chapter dan convert ke PDF.
        """
        try:
            chapter_match = re.search(r'/(?:chapter|ch)-(\d+(?:\.\d+)?)', chapter_url)
            chapter_num = chapter_match.group(1) if chapter_match else "unknown"
            print(f"📄 Downloading Chapter {chapter_num}...")
            
            driver = self.setup_driver(enable_images=True)
            if not driver:
                return 0
            
            driver.get("https://toonily.com/")
            self.handle_age_verification(driver)
            driver.get(chapter_url)
            self.handle_age_verification(driver)
            time.sleep(3)
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            no_change_count = 0
            max_scrolls = 15
            for _ in range(max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    no_change_count += 1
                    if no_change_count >= 3:
                        break
                else:
                    no_change_count = 0
                last_height = new_height
            
            driver.execute_script("""
                document.querySelectorAll('img[data-src]').forEach(img => {
                    img.src = img.getAttribute('data-src');
                    img.removeAttribute('data-src');
                });
                document.querySelectorAll('img[data-lazy-src]').forEach(img => {
                    img.src = img.getAttribute('data-lazy-src');
                    img.removeAttribute('data-lazy-src');
                });
                document.querySelectorAll('img[data-original]').forEach(img => {
                    img.src = img.getAttribute('data-original');
                    img.removeAttribute('data-original');
                });
                document.querySelectorAll('img[data-wpfc-original-src]').forEach(img => {
                    img.src = img.getAttribute('data-wpfc-original-src');
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
            time.sleep(5)
            
            html = driver.page_source
            cookies = driver.get_cookies()
            for cookie in cookies:
                self.session.cookies.set(cookie['name'], cookie['value'])
            driver.quit()
            
            soup = BeautifulSoup(html, 'html.parser')
            image_selectors = [
                '.reading-content img',
                '.chapter-type-manga .c-blog-post .entry-content .entry-content_wrap .reading-content img',
                '#readerarea img', '.entry-content img', '.wp-block-image img',
                '.chapter-content img', '.content img'
            ]
            
            images = []
            for selector in image_selectors:
                found_images = soup.select(selector)
                if found_images:
                    images.extend(found_images)
                    break
            
            if not images:
                images = soup.find_all('img', src=True)
            
            valid_images = []
            skip_keywords = [
                'icon', 'logo', 'avatar', 'thumb', 'thumbnail', 'banner', 
                'ads', 'advertisement', 'discord', 'apply', 'header', 'footer',
                'sidebar', 'menu', 'navigation', 'social', 'share', 'promo',
                'comment', 'user', 'profile', 'loading', 'spinner'
            ]
            
            for img in images:
                src = (img.get('src') or img.get('data-src') or 
                       img.get('data-lazy-src') or img.get('data-original') or 
                       img.get('data-wpfc-original-src'))
                if not src:
                    continue
                if src.startswith("data:image") and len(src) < 1000:
                    continue
                if not src.startswith(('http://', 'https://', 'data:')):
                    src = urllib.parse.urljoin(chapter_url, src)
                src_lower = src.lower()
                if any(keyword in src_lower for keyword in skip_keywords):
                    continue
                if img.get('width') and img.get('height'):
                    try:
                        width = int(img.get('width'))
                        height = int(img.get('height'))
                        if width < 100 or height < 100:
                            continue
                    except:
                        pass
                if (any(ext in src_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or 
                    src.startswith("data:image")):
                    valid_images.append(src)
            
            valid_images = list(set(valid_images))
            if not valid_images:
                print(f"⚠️ Chapter {chapter_num}: No valid images found")
                return 0
            
            chapter_folder = os.path.join(comic_folder, f"Chapter_{chapter_num.replace('.', '_').zfill(3)}")
            os.makedirs(chapter_folder, exist_ok=True)
            print(f"💾 Found {len(valid_images)} pages, downloading...")
            
            self.stats['downloaded'] = 0
            self.stats['failed'] = 0
            self.stats['total_size'] = 0
            
            download_tasks = []
            for i, img_src in enumerate(valid_images):
                ext = '.jpg' if 'jpeg' in img_src.lower() or 'jpg' in img_src.lower() else \
                      '.png' if 'png' in img_src.lower() else \
                      '.webp' if 'webp' in img_src.lower() else '.jpg'
                filename = f"page_{(i+1):03d}{ext}"
                filepath = os.path.join(chapter_folder, filename)
                download_tasks.append((img_src, filepath, chapter_url))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self.download_single_image, task) for task in download_tasks]
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    completed += 1
                    progress = completed / len(futures) * 100
                    print(f"\r💾 Progress: {progress:.0f}% ({self.stats['downloaded']}/{len(download_tasks)})", end='')
            
            print()
            downloaded = self.stats['downloaded']
            failed = self.stats['failed']
            size_mb = self.stats['total_size'] / (1024 * 1024)
            
            if downloaded > 0:
                print(f"✅ Chapter {chapter_num}: {downloaded}/{len(valid_images)} pages ({size_mb:.1f}MB)")
                if failed > 0:
                    print(f"⚠️ {failed} pages failed")
                
                # KONVERSI KE PDF SETELAH DOWNLOAD BERHASIL
                pdf_path = self.create_pdf_from_chapter(chapter_folder, comic_title, chapter_num)
                
                return downloaded
            else:
                print(f"❌ Chapter {chapter_num}: Download failed")
                return 0
        except Exception as e:
            print(f"❌ Chapter {chapter_num}: Error - {e}")
            return 0
    
    def download_comic(self, series_url, start_chapter=None, end_chapter=None):
        try:
            print("🚀 Starting download...")
            start_time = time.time()
            comic_title = self.get_comic_title(series_url)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            comic_folder = os.path.join(current_dir, "Comics", comic_title)
            os.makedirs(comic_folder, exist_ok=True)
            
            chapter_links = self.get_chapter_links(series_url)
            if not chapter_links:
                print("❌ No chapters found!")
                return
            
            if start_chapter is not None or end_chapter is not None:
                filtered_links = []
                for link in chapter_links:
                    chapter_match = re.search(r'/(?:chapter|ch)-(\d+(?:\.\d+)?)', link)
                    if chapter_match:
                        chapter_num = float(chapter_match.group(1))
                        if start_chapter is not None and chapter_num < start_chapter:
                            continue
                        if end_chapter is not None and chapter_num > end_chapter:
                            continue
                        filtered_links.append(link)
                chapter_links = filtered_links
            
            if not chapter_links:
                print("❌ No chapters in specified range!")
                return
            
            print(f"📥 Downloading {len(chapter_links)} chapters...")
            total_downloaded = 0
            success_chapters = 0
            failed_chapters = []
            
            for i, chapter_url in enumerate(chapter_links, 1):
                print(f"\n📖 Chapter {i}/{len(chapter_links)}")
                # PERUBAHAN: Kirim comic_title ke method
                downloaded = self.download_chapter_images(chapter_url, comic_folder, comic_title)
                if downloaded > 0:
                    success_chapters += 1
                    total_downloaded += downloaded
                else:
                    chapter_match = re.search(r'/(?:chapter|ch)-(\d+(?:\.\d+)?)', chapter_url)
                    chapter_num = chapter_match.group(1) if chapter_match else "unknown"
                    failed_chapters.append(chapter_num)
                time.sleep(1)
            
            elapsed_time = time.time() - start_time
            print("\n🎉 Download Complete!")
            print(f"✅ Success: {success_chapters}/{len(chapter_links)} chapters")
            print(f"📊 Total pages: {total_downloaded}")
            print(f"⏱️ Time: {elapsed_time:.1f}s ({elapsed_time/60:.1f}min)")
            if total_downloaded > 0:
                print(f"⚡ Speed: {total_downloaded/elapsed_time:.1f} pages/second")
            if failed_chapters:
                print(f"❌ Failed chapters: {', '.join(f'Chapter {num}' for num in failed_chapters)}")
            try:
                folder_size = sum(os.path.getsize(os.path.join(root, f)) 
                                for root, _, files in os.walk(comic_folder) 
                                for f in files) / (1024 * 1024)
                print(f"💾 Total size: {folder_size:.1f}MB")
            except Exception:
                pass
            print(f"📁 Saved to: {comic_folder}")
        except Exception as e:
            print(f"❌ Download error: {e}")

def main():
    downloader = ToonilyComicDownloader()
    print("📚 TOONILY Comic Downloader")
    series_url = input("Enter Toonily comic URL: ").strip()
    
    if not series_url:
        print("❌ URL required!")
        return
    if not series_url.startswith('http'):
        series_url = 'https://' + series_url
    if 'toonily.com' not in series_url:
        print("⚠️ This downloader is optimized for toonily.com")
        proceed = input("Continue anyway? (y/n): ").lower()
        if proceed != 'y':
            return
    
    print("\nOptions:\n1. All chapters\n2. Specific range\n3. Latest chapters")
    choice = input("Choose (1, 2, or 3): ").strip()
    start_chapter = None
    end_chapter = None
    
    if choice == '2':
        try:
            start_input = input("Start chapter (or Enter for beginning): ").strip()
            end_input = input("End chapter (or Enter for latest): ").strip()
            if start_input:
                start_chapter = float(start_input)
            if end_input:
                end_chapter = float(end_input)
            if start_chapter and end_chapter and start_chapter > end_chapter:
                print("❌ Invalid range!")
                return
        except ValueError:
            print("❌ Invalid numbers. Downloading all chapters.")
    
    elif choice == '3':
        try:
            latest_count = input("How many latest chapters? (default: 5): ").strip()
            latest_count = int(latest_count) if latest_count else 5
            print(f"📥 Will download the latest {latest_count} chapters")
            
            temp_downloader = ToonilyComicDownloader()
            driver = temp_downloader.setup_driver(enable_images=False)
            if driver:
                try:
                    driver.get("https://toonily.com/")
                    temp_downloader.handle_age_verification(driver)
                    driver.get(series_url)
                    temp_downloader.handle_age_verification(driver)
                    time.sleep(3)
                    html = driver.page_source
                    driver.quit()
                    soup = BeautifulSoup(html, 'html.parser')
                    chapter_links = []
                    selectors = [
                        'body.manga-page .page-content-listing.single-page .listing-chapters_wrap ul.main li a',
                        'ul.main li a', '.wp-manga-chapter a'
                    ]
                    for selector in selectors:
                        links = soup.select(selector)
                        if links:
                            for link in links:
                                href = link.get('href', '')
                                if href and ('/chapter-' in href or '/ch-' in href):
                                    chapter_links.append(href)
                            break
                    if chapter_links:
                        def extract_chapter_num(url):
                            match = re.search(r'/(?:chapter|ch)-(\d+(?:\.\d+)?)', url)
                            return float(match.group(1)) if match else 0
                        chapter_links.sort(key=extract_chapter_num, reverse=True)
                        if len(chapter_links) >= latest_count:
                            latest_chapters = chapter_links[:latest_count]
                            chapter_nums = [extract_chapter_num(url) for url in latest_chapters]
                            start_chapter = min(chapter_nums)
                            end_chapter = max(chapter_nums)
                            print(f"📋 Latest chapters: {start_chapter} to {end_chapter}")
                        else:
                            print(f"📋 Found only {len(chapter_links)} chapters, downloading all")
                except Exception as e:
                    print(f"⚠️ Error determining latest chapters: {e}")
        except ValueError:
            print("❌ Invalid number. Downloading all chapters.")
    
    try:
        downloader.download_comic(series_url, start_chapter, end_chapter)
    except KeyboardInterrupt:
        print("\n❌ Download cancelled")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()