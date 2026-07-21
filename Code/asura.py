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
import urllib.parse
import re
from pathlib import Path
from webdriver_manager.chrome import ChromeDriverManager
import logging
import concurrent.futures
from threading import Lock
import threading

# Setup minimal logging
logging.basicConfig(level=logging.ERROR, format='❌ %(message)s')
logger = logging.getLogger(__name__)

# Suppress logs
for logger_name in ['WDM', 'selenium', 'urllib3']:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

class OptimizedAsuraComicDownloader:
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
        
        # Threading controls untuk download
        self.max_workers = 6  # Reduced untuk stabilitas
        self.download_lock = Lock()
        self.stats = {
            'downloaded': 0,
            'failed': 0,
            'total_size': 0
        }
        
        # Session untuk downloads
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
    def setup_driver(self):
        """Setup Chrome driver dengan optimasi"""
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
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--allow-insecure-localhost")
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument("--silent")
            
            # Disable images for chapter list (faster), enable for image download
            prefs = {
                "profile.managed_default_content_settings.images": 2,  # Start dengan images disabled
                "profile.default_content_setting_values.notifications": 2
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            service.log_path = os.devnull
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": self.headers['User-Agent']
            })
            
            return driver
        except Exception as e:
            print(f"❌ Error setting up driver: {e}")
            return None
    
    def clean_filename(self, filename):
        """Bersihkan nama file dari karakter yang tidak valid"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = re.sub(r'\s+', ' ', filename).strip()
        return filename[:100]
        
    def get_comic_title(self, series_url):
        """Ambil judul komik dari halaman series"""
        try:
            print("📖 Getting comic information...")
            driver = self.setup_driver()
            if not driver:
                return "Unknown_Comic"
            
            driver.get(series_url)
            wait = WebDriverWait(driver, 10)
            
            title_selectors = [
                'h1.text-xl',
                'h1',
                '.series-title',
                '.comic-title',
                '[data-testid="series-title"]',
                '.entry-title',
                '.post-title',
                'h1.entry-title'
            ]
            
            title = None
            for selector in title_selectors:
                try:
                    title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
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
        """Ambil semua link chapter dengan smart scroll"""
        try:
            driver = self.setup_driver()
            if not driver:
                return []
            
            print("🔍 Scanning for chapters...")
            driver.get(series_url)
            time.sleep(2)
            
            # Smart scroll dengan early termination
            print("   Loading chapters...", end='', flush=True)
            last_height = driver.execute_script("return document.body.scrollHeight")
            no_change_count = 0
            max_no_change = 3
            
            while no_change_count < max_no_change:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)  # Reduced from 2s
                new_height = driver.execute_script("return document.body.scrollHeight")
                
                if new_height == last_height:
                    no_change_count += 1
                else:
                    no_change_count = 0
                    
                last_height = new_height
                print(".", end='', flush=True)
            
            print(" ✅")
            
            # Try clicking load more buttons
            try:
                load_more_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Load') or contains(text(), 'More') or contains(text(), 'Show')]")
                for button in load_more_buttons:
                    try:
                        driver.execute_script("arguments[0].click();", button)
                        time.sleep(1)
                    except:
                        pass
            except:
                pass
            
            html = driver.page_source
            driver.quit()
            
            soup = BeautifulSoup(html, 'html.parser')
            chapter_links = []
            
            chapter_patterns = [
                r'/chapter/\d+',
                r'/ch/\d+',
                r'/chapter-\d+',
                r'/ch-\d+',
                r'chapter/\d+',
                r'chapter-\d+'
            ]
            
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                for pattern in chapter_patterns:
                    if re.search(pattern, href):
                        full_url = urllib.parse.urljoin(series_url, href)
                        chapter_links.append(full_url)
                        break
            
            chapter_links = list(set(chapter_links))
            
            def extract_chapter_num(url):
                patterns = [r'/chapter/(\d+)', r'/ch/(\d+)', r'/chapter-(\d+)', r'/ch-(\d+)', r'chapter/(\d+)', r'chapter-(\d+)']
                for pattern in patterns:
                    match = re.search(pattern, url)
                    if match:
                        return int(match.group(1))
                return 0
            
            chapter_links.sort(key=extract_chapter_num)
            print(f"📋 Found {len(chapter_links)} chapters")
            return chapter_links
            
        except Exception as e:
            print(f"❌ Error getting chapter links: {e}")
            return []
    
    def download_single_image(self, img_data):
        """Download single image dengan optimasi"""
        img_src, filepath = img_data
        
        try:
            # Gunakan session yang sudah ada
            response = self.session.get(img_src, stream=True, timeout=20)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            
            with self.download_lock:
                self.stats['downloaded'] += 1
                self.stats['total_size'] += file_size
            
            return True
            
        except Exception as e:
            with self.download_lock:
                self.stats['failed'] += 1
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            return False
    
    def download_chapter_images(self, chapter_url, comic_folder):
        """Download gambar dari chapter - TETAP MENGGUNAKAN SELENIUM untuk compatibility"""
        try:
            chapter_match = re.search(r'/chapter[/-]?(\d+)', chapter_url)
            if not chapter_match:
                chapter_match = re.search(r'/ch[/-]?(\d+)', chapter_url)
            
            chapter_num = chapter_match.group(1) if chapter_match else "unknown"
            
            # Setup driver untuk chapter ini (enable images)
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument("--log-level=3")
            
            # ENABLE images untuk chapter download
            prefs = {
                "profile.managed_default_content_settings.images": 1,  # Enable images
                "profile.default_content_setting_values.notifications": 2
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            service.log_path = os.devnull
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            print(f"📄 Loading Chapter {chapter_num}...", end='', flush=True)
            driver.get(chapter_url)
            time.sleep(2)  # Reduced wait time
            
            # Optimized scroll - lebih cepat
            scroll_pause_time = 1  # Reduced from 1.5
            last_height = driver.execute_script("return document.body.scrollHeight")
            max_scrolls = 10  # Reduced from 15
            no_change_count = 0
            
            for scroll_count in range(max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_pause_time)
                new_height = driver.execute_script("return document.body.scrollHeight")
                
                if new_height == last_height:
                    no_change_count += 1
                    if no_change_count >= 2:  # Stop scrolling if no change for 2 attempts
                        break
                else:
                    no_change_count = 0
                    
                last_height = new_height
                print(".", end='', flush=True)
            
            print(" ✅")
            
            # Force load lazy images (same as original)
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
            """)
            time.sleep(1)  # Reduced wait
            
            html = driver.page_source
            driver.quit()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Prioritaskan selector untuk halaman chapter, hindari related series
            image_selectors = [
                'div#readerarea img',
                '.reading-content img',
                '.chapter-content img',
                '.reader img',
                '#chapter img'
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
            # Kata kunci untuk mendeteksi gambar "closing" atau "end"
            end_keywords = [
                'end', 'closing', 'to be continued', 'tbc', 'finish', 'complete',
                'chapter_end', 'chapter-end', 'final', 'conclusion', 'last',
                'final_page', 'chapter_close', 'done', 'over'
            ]
            # Perluas skip_keywords untuk iklan dan konten tidak relevan
            skip_keywords = [
                'icon', 'logo', 'avatar', 'thumb', 'thumbnail', 'banner', 
                'ads', 'advertisement', 'discord', 'apply', 'header', 'footer',
                'sidebar', 'menu', 'navigation', 'social', 'share', 'promo', 
                'ad', 'support', 'patreon', 'donate', 'emoji', 'related', 'series'
            ]
            max_pages = 20  # Batas maksimum halaman per chapter (sesuaikan dengan situs)
            last_page_num = 0  # Untuk melacak nomor halaman terakhir
            
            for img in images:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original')
                if not src:
                    continue
                
                src = urllib.parse.urljoin(chapter_url, src)
                
                # Skip non-content images
                if any(keyword in src.lower() for keyword in skip_keywords):
                    continue
                
                # Check for "EndDesign.webp" as the specific end indicator
                if src == 'https://asuracomic.net/images/EndDesign.webp':
                    valid_images.append(src)
                    break  # Hentikan pengumpulan setelah menemukan EndDesign.webp
                
                # Check for "closing" or "end" indicators as fallback
                alt = img.get('alt', '').lower()
                if any(keyword in alt.lower() for keyword in end_keywords) or \
                   any(keyword in src.lower() for keyword in end_keywords):
                    valid_images.append(src)
                    break  # Hentikan pengumpulan setelah menemukan "end"
                
                # Check if it's likely a page image
                if 'page' in alt or any(f'page {i}' in alt for i in range(1, max_pages + 1)):
                    # Ekstrak nomor halaman dari alt atau src
                    page_match = re.search(r'page\s*(\d+)', alt, re.IGNORECASE)
                    if not page_match:
                        page_match = re.search(r'page[-_]?(\d+)', src, re.IGNORECASE)
                    
                    if page_match:
                        page_num = int(page_match.group(1))
                        if page_num > last_page_num:
                            last_page_num = page_num
                            valid_images.append(src)
                        else:
                            # Jika nomor halaman tidak bertambah, hentikan
                            break
                    else:
                        valid_images.append(src)
                    continue
                
                # Simplified check - hanya tambahkan jika format gambar valid
                if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    valid_images.append(src)
                
                # Hentikan jika mencapai batas maksimum halaman atau mendeteksi related series
                if len(valid_images) >= max_pages:
                    break
                # Cek sibling untuk mendeteksi perubahan konteks (related series)
                parent = img.find_parent()
                if parent and any('related' in sibling.get_text().lower() or 'series' in sibling.get_text().lower() 
                                for sibling in parent.find_next_siblings() if sibling.get_text()):
                    break
            
            # Remove duplicates
            seen = set()
            unique_images = []
            for img in valid_images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            valid_images = unique_images
            
            if not valid_images:
                print(f"⚠️  Chapter {chapter_num}: No images found")
                return 0
            
            # Create chapter folder dengan path baru: comics/nama_comic/chapters/chapter_xxx
            chapters_dir = os.path.join(comic_folder, "chapters")
            chapter_folder = os.path.join(chapters_dir, f"chapter_{chapter_num.zfill(3)}")
            os.makedirs(chapter_folder, exist_ok=True)
            
            print(f"💾 Downloading {len(valid_images)} pages with {self.max_workers} threads...", end='', flush=True)
            
            # Reset stats
            self.stats['downloaded'] = 0
            self.stats['failed'] = 0
            self.stats['total_size'] = 0
            
            # Prepare download tasks
            download_tasks = []
            for i, img_src in enumerate(valid_images):
                # Determine file extension
                content_type = ''
                if 'jpeg' in img_src.lower() or 'jpg' in img_src.lower():
                    ext = '.jpg'
                elif 'png' in img_src.lower():
                    ext = '.png'
                elif 'webp' in img_src.lower():
                    ext = '.webp'
                else:
                    ext = '.jpg'
                
                filename = f"page_{(i+1):03d}{ext}"
                filepath = os.path.join(chapter_folder, filename)
                download_tasks.append((img_src, filepath))
            
            # Multi-threaded download
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self.download_single_image, task) for task in download_tasks]
                
                # Progress tracking
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    completed += 1
                    progress = completed / len(futures) * 100
                    if completed % 3 == 0 or completed == len(futures):
                        print(f"\r💾 Downloading: {progress:.0f}% ({self.stats['downloaded']}/{len(download_tasks)})", end='', flush=True)
            
            print()  # New line
            
            downloaded = self.stats['downloaded']
            failed = self.stats['failed']
            size_mb = self.stats['total_size'] / (1024 * 1024)
            
            if downloaded > 0:
                print(f"✅ Chapter {chapter_num}: {downloaded}/{len(valid_images)} pages ({size_mb:.1f}MB)")
                if failed > 0:
                    print(f"   ⚠️  {failed} pages failed")
                return downloaded
            else:
                print(f"❌ Chapter {chapter_num}: Download failed")
                return 0
                
        except Exception as e:
            print(f"❌ Chapter {chapter_num}: Error - {e}")
            return 0
    
    def download_comic(self, series_url, start_chapter=None, end_chapter=None):
        """Download seluruh komik dengan optimasi"""
        try:
            print("🚀 Starting optimized download...")
            start_time = time.time()
            
            # Get comic title
            comic_title = self.get_comic_title(series_url)
            
            # Create comic folder dengan struktur baru: comics/nama_comic/
            current_dir = os.path.dirname(os.path.abspath(__file__))
            comics_main_dir = os.path.join(current_dir, "comics")
            comic_folder = os.path.join(comics_main_dir, comic_title)
            os.makedirs(comic_folder, exist_ok=True)
            
            # Create chapters subdirectory
            chapters_dir = os.path.join(comic_folder, "chapters")
            os.makedirs(chapters_dir, exist_ok=True)
            
            # Get chapter links
            chapter_links = self.get_chapter_links(series_url)
            
            if not chapter_links:
                print("❌ No chapters found!")
                return
            
            # Filter chapters if range specified
            if start_chapter is not None or end_chapter is not None:
                filtered_links = []
                for link in chapter_links:
                    chapter_patterns = [r'/chapter[/-]?(\d+)', r'/ch[/-]?(\d+)']
                    chapter_num = None
                    
                    for pattern in chapter_patterns:
                        match = re.search(pattern, link)
                        if match:
                            chapter_num = int(match.group(1))
                            break
                    
                    if chapter_num is not None:
                        if start_chapter is not None and chapter_num < start_chapter:
                            continue
                        if end_chapter is not None and chapter_num > end_chapter:
                            continue
                        filtered_links.append(link)
                
                chapter_links = filtered_links
            
            if not chapter_links:
                print("❌ No chapters in specified range!")
                return
            
            print(f"📥 Downloading {len(chapter_links)} chapters with multi-threading")
            print("=" * 60)
            
            # Download chapters
            total_downloaded = 0
            success_chapters = 0
            failed_chapters = []
            
            for i, chapter_url in enumerate(chapter_links, 1):
                print(f"\n📖 Progress: {i}/{len(chapter_links)}")
                
                downloaded = self.download_chapter_images(chapter_url, comic_folder)
                if downloaded > 0:
                    success_chapters += 1
                    total_downloaded += downloaded
                else:
                    # Extract chapter number for failed chapters
                    chapter_match = re.search(r'/chapter[/-]?(\d+)', chapter_url) or re.search(r'/ch[/-]?(\d+)', chapter_url)
                    chapter_num = chapter_match.group(1) if chapter_match else "unknown"
                    failed_chapters.append(chapter_num)
                
                # Minimal rate limiting
                time.sleep(0.2)  # Reduced from 1s
            
            # Final Summary
            elapsed_time = time.time() - start_time
            print("\n" + "=" * 60)
            print("🎉 Optimized Download Complete!")
            print(f"✅ Success: {success_chapters}/{len(chapter_links)} chapters")
            print(f"📊 Total pages: {total_downloaded}")
            print(f"⏱️  Total time: {elapsed_time:.1f}s ({elapsed_time/60:.1f}min)")
            
            if total_downloaded > 0:
                print(f"⚡ Speed: {total_downloaded/elapsed_time:.1f} pages/second")
            
            if failed_chapters:
                print(f"❌ Failed chapters: {', '.join(f'Chapter {num}' for num in failed_chapters)}")
            
            folder_size = sum(os.path.getsize(os.path.join(root, f)) 
                            for root, _, files in os.walk(comic_folder) 
                            for f in files) / (1024 * 1024)
            print(f"💾 Total size: {folder_size:.1f}MB")
            print(f"📁 Saved to: {comic_folder}")
            
        except Exception as e:
            print(f"❌ Download error: {e}")

def main():
    downloader = OptimizedAsuraComicDownloader()
    
    print("⚡ OPTIMIZED AsuraComic Downloader v2.1")
    print("🚀 Features: Multi-threading, Smart scroll, Faster processing")
    print("📁 New Structure: comics/nama_comic/chapters/chapter_xxx/")
    print("=" * 50)
    
    series_url = input("Enter comic URL: ").strip()
    
    if not series_url:
        print("❌ URL required!")
        return
    
    if not series_url.startswith('http'):
        series_url = 'https://' + series_url
    
    print("\nOptions:")
    print("1. Download all chapters")
    print("2. Download specific range")
    
    choice = input("Choose (1 or 2): ").strip()
    
    start_chapter = None
    end_chapter = None
    
    if choice == '2':
        try:
            start_input = input("Start chapter (or Enter for all): ").strip()
            end_input = input("End chapter (or Enter for latest): ").strip()
            
            if start_input:
                start_chapter = int(start_input)
            if end_input:
                end_chapter = int(end_input)
                
            if start_chapter and end_chapter and start_chapter > end_chapter:
                print("❌ Invalid range!")
                return
        except ValueError:
            print("❌ Invalid numbers. Downloading all chapters.")
    
    try:
        downloader.download_comic(series_url, start_chapter, end_chapter)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    main)