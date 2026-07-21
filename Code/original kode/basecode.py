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

# URL of your comic
url = "https://hentairead.com/hentai/1ldk-plus-jk-ikinari-doukyo-micchaku-hatsu-ecchi/english/p/"

# Setup Chrome in headless mode
chrome_options = Options()
chrome_options.add_argument("--headless=new")  # headless mode (invisible)
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

# Create folder to save images
os.makedirs("comic_images", exist_ok=True)

# Download images
count = 0
for img in images:
    src = img.get("src")
    if not src:
        continue

    img_url = urllib.parse.urljoin(url, src)
    try:
        img_data = requests.get(img_url).content
        with open(f"comic_images/page_{count:04}.jpg", "wb") as f:
            f.write(img_data)
        print(f"✅ Downloaded page {count}")
        count += 1
    except Exception as e:
        print(f"❌ Error downloading {img_url}: {e}")

print(f"\n🎉 Done! {count} pages downloaded to 'comic_images/' folder.")
