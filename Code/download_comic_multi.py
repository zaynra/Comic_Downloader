from comic_downloader import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import requests
import os
import time
import urllib.parse
from PIL import Image
from PIL.ImageEnhance import Sharpness, Contrast, Brightness
import shutil

def download_and_enhance_images(url, original_folder, enhanced_folder):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x6000")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)

    scroll_pause_time = 2
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")

    os.makedirs(original_folder, exist_ok=True)
    os.makedirs(enhanced_folder, exist_ok=True)

    count = 0
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for img in images:
        src = img.get("src")
        if not src:
            continue

        img_url = urllib.parse.urljoin(url, src)
        try:
            response = requests.get(img_url, headers=headers, stream=True, timeout=10)
            response.raise_for_status()
            
            original_path = os.path.join(original_folder, f"page_{count:04}.jpg")
            with open(original_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ Downloaded original: page_{count:04}.jpg")

            img = Image.open(original_path).convert("RGB")
            enhanced_img = img.resize((int(img.width * 2), int(img.height * 2)), Image.Resampling.LANCZOS)
            sharpener = Sharpness(enhanced_img)
            enhanced_img = sharpener.enhance(2.0)
            contrast = Contrast(enhanced_img)
            enhanced_img = contrast.enhance(1.5)
            brightness = Brightness(enhanced_img)
            enhanced_img = brightness.enhance(1.2)
            enhanced_path = os.path.join(enhanced_folder, f"enhanced_page_{count:04}.jpg")
            enhanced_img.save(enhanced_path, quality=95, optimize=True)
            print(f"✅ Enhanced and saved: enhanced_page_{count:04}.jpg")

            os.remove(original_path)
            count += 1

        except requests.RequestException as e:
            print(f"❌ Error downloading {img_url}: {e}")
        except Exception as e:
            print(f"❌ Error processing image {count}: {e}")

    if os.path.exists(original_folder):
        shutil.rmtree(original_folder)
        print(f"🗑️ Removed temporary folder: {original_folder}")

    print(f"\n🎉 Done! {count} pages downloaded, enhanced, and saved to '{enhanced_folder}' folder.\n")

def main():
    print("🖼️ Masukkan satu atau beberapa URL komik (pisahkan dengan koma):")
    user_input = input("URL(s): ")

    urls = [u.strip() for u in user_input.split(",") if u.strip()]
    if not urls:
        print("❌ Tidak ada URL yang dimasukkan. Keluar.")
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))

    for idx, url in enumerate(urls, start=1):
        print(f"\n🚀 Memproses URL {idx}: {url}")
        original_folder = os.path.join(current_dir, f"comic_images_{idx}")
        enhanced_folder = os.path.join(current_dir, f"enhanced_images_{idx}")
        download_and_enhance_images(url, original_folder, enhanced_folder)

    print("\n✅ Semua komik selesai diproses!")

if __name__ == "__main__":
    main()
