from pathlib import Path
from seleniumwire import webdriver 
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import json

CONFIG_FILE = Path.home() / "926data_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

config = load_config(CONFIG_FILE)

BASE_URL = config.get("BASE_URL")

INPUT_FILE = "926page_source.html"
OUTPUT_FILE = "map4.json"

def normalize_m3u8_url(url):
    parsed = urlparse(url.lower())
    qs = parse_qs(parsed.query)
    for param in ['txsecret', 'txtime', '_']:
        qs.pop(param, None)
    new_query = urlencode(qs, doseq=True)
    path = parsed.path.rstrip('/')
    return urlunparse(parsed._replace(path=path, query=new_query)).strip()

with open(INPUT_FILE, encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

live_ids = [a["href"].split("/")[-1] for a in soup.find_all("a", href=True) if a["href"].startswith("/bofang/")]

print(f"Found {len(live_ids)} live IDs:", live_ids)

options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--mute-audio")
if config.get("USER_AGENT"):
    options.add_argument(f'user-agent={config["USER_AGENT"]}')

driver = webdriver.Chrome(options=options)

previous_url_norm = None
placeholder_active = False
results = {}

try:
    for lid in live_ids:
        url = f"{BASE_URL}/live/{lid}"
        print(f"🎯 Live URL: {url}")

        if placeholder_active:
            print(f"   ⚠️ Placeholder aktif, ID {lid} di-skip")
            continue

        driver.request_interceptor = None
        driver.get("about:blank")
        driver.requests.clear()

        driver.get(url)

        try:
            # Tunggu elemen player muncul (ganti selector sesuai kebutuhan)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "video, .player, .live-container"))
            )
        except:
            print("   ⚠️ Timeout tunggu elemen player")

        time.sleep(3)  # tambahan tunggu stabil

        m3u8_links = [req.url for req in driver.requests if req.response and ".m3u8" in req.url]

        if not m3u8_links:
            print("   ❌ Tidak ditemukan .m3u8")
            continue

        final_link = m3u8_links[-1]
        final_link_norm = normalize_m3u8_url(final_link)

        if previous_url_norm == final_link_norm:
            print(f"   ⚠️ URL sama dengan sebelumnya, aktifkan placeholder dan skip ID ini")
            placeholder_active = True
            continue

        print(f"   ✅ Found .m3u8: {final_link}")
        results[lid] = final_link.strip()
        previous_url_norm = final_link_norm

finally:
    driver.quit()

print("\n📦 Ringkasan hasil:")
for lid, link in results.items():
    print(f"{lid}: {link}")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Hasil disimpan ke {OUTPUT_FILE}")
