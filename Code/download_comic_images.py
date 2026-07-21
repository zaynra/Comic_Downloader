from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import requests
import os
import time
import urllib.parse
import shutil

def download_images(url, original_folder):
    # Setup Chrome in headless mode
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x6000")

    # Launch Chrome browser
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)

    # Scroll to the bottom of the page slowly
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

    # Create folder to save original images
    os.makedirs(original_folder, exist_ok=True)

    # Download images
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

            # Save original image
            original_path = os.path.join(original_folder, f"page_{count:04}.jpg")
            with open(original_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ Downloaded original: page_{count:04}.jpg")

            count += 1

        except requests.RequestException as e:
            print(f"❌ Error downloading {img_url}: {e}")
        except Exception as e:
            print(f"❌ Error processing image {count}: {e}")

    # Cleanup
    print(f"\n🎉 Done! {count} pages downloaded and saved to '{original_folder}' folder.")

def main():
    url = input("Enter the website URL with comic images: ")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    original_folder = os.path.join(current_dir, "comic_images")
    download_images(url, original_folder)

if __name__ == "__main__":
    main()