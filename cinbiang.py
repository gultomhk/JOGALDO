from pathlib import Path
from seleniumwire.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time, re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import json, sys
from webdriver_manager.chrome import ChromeDriverManager

# --- Config ---
CONFIG_FILE = Path.home() / "926data_file.txt"
OUTPUT_FILE = "map4.json"

def load_config(filepath):
    config = {}
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    config[key.strip()] = val.strip().strip('"')
    except FileNotFoundError:
        print(f"❌ Config file not found at {filepath}")
        sys.exit(1)
    return config

config = load_config(CONFIG_FILE)

BASE_URL = config.get("BASE_URL")
if not BASE_URL:
    print("❌ BASE_URL not found in config")
    sys.exit(1)

# --- Normalizer (untuk deteksi duplikat) ---
def normalize_m3u8_url(url):
    try:
        parsed = urlparse(url.lower())
        qs = parse_qs(parsed.query)
        for param in ['txsecret', 'txtime', '_']:
            qs.pop(param, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(path=parsed.path.rstrip('/'), query=new_query)).strip()
    except Exception as e:
        print(f"⚠️ Error normalizing URL {url}: {e}")
        return url

# --- Setup Chrome ---
options = Options()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--mute-audio")
if config.get("USER_AGENT"):
    options.add_argument(f'user-agent={config["USER_AGENT"]}')

seleniumwire_options = {'disable_encoding': True}

try:
    service = Service(ChromeDriverManager().install())
    driver = Chrome(service=service, options=options, seleniumwire_options=seleniumwire_options)
except Exception as e:
    print(f"❌ Failed to initialize Chrome WebDriver: {e}")
    sys.exit(1)

# --- Ambil daftar live IDs langsung dari BASE_URL ---
print(f"🔍 Mengambil daftar live dari {BASE_URL} ...")
driver.get(BASE_URL)
time.sleep(3)  # tunggu render awal
soup = BeautifulSoup(driver.page_source, "html.parser")
live_ids = [a["href"].split("/")[-1] for a in soup.find_all("a", href=True) if a["href"].startswith("/bofang/")]
print(f"Found {len(live_ids)} live IDs:", live_ids)

previous_url_norm = None
placeholder_active = False
results = {}

try:
    for lid in live_ids:
        url = f"{BASE_URL}/live/{lid}"
        print(f"\n🎯 Live URL: {url}")

        if placeholder_active:
            print(f"   ⚠️ Placeholder aktif, ID {lid} di-skip")
            continue

        driver.get("about:blank")
        time.sleep(0.5)
        driver.requests.clear()

        try:
            driver.get(url)
        except Exception as e:
            print(f"   ❌ Gagal load halaman: {e}")
            placeholder_active = True
            continue

        # Tunggu elemen player
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "video, iframe, .player, .live-container"))
            )
            print("   ℹ️ Player terdeteksi")
        except:
            print("   ⚠️ Player tidak ditemukan dalam 15 detik")
            placeholder_active = True
            continue

        # Ambil m3u8 dari request network
        m3u8_links = []
        start = time.time()
        while time.time() - start < 15:
            m3u8_links = [req.url for req in driver.requests if req.response and ".m3u8" in req.url]
            if m3u8_links:
                break
            time.sleep(1)

        # Fallback regex
        if not m3u8_links:
            found = re.findall(r"https?://[^\s'\"]+\.m3u8[^\s'\"]*", driver.page_source)
            if found:
                m3u8_links = found

        if not m3u8_links:
            print("   ❌ Tidak ditemukan .m3u8")
            placeholder_active = True
            continue

        final_link = m3u8_links[-1]
        final_link_norm = normalize_m3u8_url(final_link)

        if previous_url_norm == final_link_norm:
            print("   ⚠️ URL sama dengan sebelumnya, aktifkan placeholder")
            placeholder_active = True
            continue

        print(f"   ✅ Found .m3u8: {final_link}")
        results[lid] = final_link.strip()
        previous_url_norm = final_link_norm

finally:
    driver.quit()

# --- Save hasil ---
print("\n📦 Ringkasan hasil:")
for lid, link in results.items():
    print(f"{lid}: {link}")

try:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Disimpan ke {OUTPUT_FILE}")
except Exception as e:
    print(f"❌ Gagal simpan hasil: {e}")
