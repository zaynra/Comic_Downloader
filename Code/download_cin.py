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
import base64
import re

def download_and_enhance_images(url, original_folder, enhanced_folder):
    # Setup Chrome in headless mode
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x6000")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # Launch Chrome browser with increased timeout
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(300)

    # Scroll to the bottom of the page slowly
    max_retries = 3
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(5)
            break
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(5)

    scroll_pause_time = 2
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    # Get page source after scrolling
    html = driver.page_source
    driver.quit()

    # Use BeautifulSoup to extract image URLs
    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")

    # Create folders to save original and enhanced images
    os.makedirs(original_folder, exist_ok=True)
    os.makedirs(enhanced_folder, exist_ok=True)

    # Download and enhance images
    count = 0
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    for img in images:
        src = img.get("src")
        if not src:
            continue

        try:
            # Check if src is a data URI
            if src.startswith("data:image"):
                # Extract base64 data
                base64_data = re.sub(r'^data:image/[^;]+;base64,', '', src)
                img_data = base64.b64decode(base64_data)
                original_path = os.path.join(original_folder, f"page_{count:04}.jpg")
                with open(original_path, "wb") as f:
                    f.write(img_data)
                print(f"✅ Decoded data URI as original: page_{count:04}.jpg")
            else:
                # Handle regular URL
                img_url = urllib.parse.urljoin(url, src)
                response = requests.get(img_url, headers=headers, stream=True, timeout=10)
                response.raise_for_status()
                original_path = os.path.join(original_folder, f"page_{count:04}.jpg")
                with open(original_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"✅ Downloaded original: page_{count:04}.jpg")

            # Enhance image quality
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

            # Remove the original file after enhancement
            os.remove(original_path)
            count += 1

        except (requests.RequestException, base64.binascii.Error, ValueError) as e:
            print(f"❌ Error processing image {count} from {src}: {e}")
            if os.path.exists(original_path):
                os.remove(original_path)

    # Remove the entire comic_images folder if empty or after processing
    if os.path.exists(original_folder):
        shutil.rmtree(original_folder)
        print(f"🗑️ Removed temporary folder: {original_folder}")

    print(f"\n🎉 Done! {count} pages downloaded, enhanced, and saved to '{enhanced_folder}' folder.")

def main():
    url = input("Enter the website URL with comic images: ")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    original_folder = os.path.join(current_dir, "comic_images")
    enhanced_folder = os.path.join(current_dir, "enhanced_images")
    download_and_enhance_images(url, original_folder, enhanced_folder)

if __name__ == "__main__":
    main()