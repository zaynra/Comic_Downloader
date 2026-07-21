from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import requests
import os
import time
import urllib.parse

def download_images(url, folder):
    # Setup Chrome in headless mode
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x6000")

    # Launch Chrome browser
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)

    # Wait for the page to load
    time.sleep(3)

    # Get page source
    html = driver.page_source
    driver.quit()

    # Use BeautifulSoup to extract image URLs
    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")

    # Create folder to save images
    os.makedirs(folder, exist_ok=True)

    # Download images
    for idx, img in enumerate(images):
        src = img.get("src")
        if not src:
            continue

        img_url = urllib.parse.urljoin(url, src)
        try:
            response = requests.get(img_url, stream=True)
            response.raise_for_status()
            
            # Save image
            image_path = os.path.join(folder, f"image_{idx+1}.jpg")
            with open(image_path, "wb") as f:
                f.write(response.content)
            print(f"✅ Downloaded: image_{idx+1}.jpg")

        except requests.RequestException as e:
            print(f"❌ Error downloading {img_url}: {e}")

def main():
    url = "https://hentaifox.com/gallery/143327/"
    folder = "hentaifox_images"
    download_images(url, folder)

if __name__ == "__main__":
    main()