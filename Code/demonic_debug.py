"""
Script DEBUG untuk demonicscans.org
Jalankan ini dulu sebelum downloader untuk tahu struktur HTML-nya.
Akan menyimpan HTML ke file debug_series.html dan debug_chapter.html
"""

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import re
import sys
import os

SERIES_URL  = "https://demonicscans.org/manga/Mairimashita%2521-Iruma%25252Dkun"
CHAPTER_URL = "https://demonicscans.org/title/Mairimashita%2521-Iruma%25252Dkun/chapter/353/1"

def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,900")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def dump_series():
    print("[1/2] Membuka halaman SERIES...")
    driver = get_driver()
    driver.get(SERIES_URL)
    time.sleep(5)

    # Scroll untuk load semua chapter
    for i in range(10):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)

    html = driver.page_source
    driver.quit()

    with open("debug_series.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  Saved: debug_series.html")

    # Analisis langsung
    soup = BeautifulSoup(html, "html.parser")
    print("\n  === SEMUA <a> href yang menarik ===")
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r'\d', href) and len(href) > 8:
            print(f"  {href}")
            count += 1
            if count >= 40:
                print("  ... (terpotong, lihat debug_series.html)")
                break

    print("\n  === Struktur tag pertama (body children) ===")
    body = soup.body
    if body:
        for child in list(body.children)[:15]:
            if hasattr(child, 'name') and child.name:
                print(f"  <{child.name} class='{child.get('class','')}'> id='{child.get('id','')}'")

    return soup

def dump_chapter():
    print("\n[2/2] Membuka halaman CHAPTER...")
    driver = get_driver()
    driver.get(CHAPTER_URL)
    time.sleep(4)

    html = driver.page_source
    driver.quit()

    with open("debug_chapter.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  Saved: debug_chapter.html")

    soup = BeautifulSoup(html, "html.parser")
    print("\n  === Semua <img> src ===")
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "")
        if src:
            print(f"  {src}")

    print("\n  === Semua <a> href ===")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if len(href) > 3:
            print(f"  {href}")

if __name__ == "__main__":
    dump_series()
    dump_chapter()
    print("\n=== SELESAI ===")
    print("Kirimkan output di atas untuk analisis lebih lanjut.")
    print("File debug_series.html dan debug_chapter.html juga disimpan.")