from pathlib import Path
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time, re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import json, sys, os, shutil
from webdriver_manager.chrome import ChromeDriverManager

CONFIG_FILE = Path.home() / "926data_file.txt"

def load_config(filepath):
    config = {}
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    config[key.strip()] = val.strip().strip('"')
    except FileNotFoundError:
        print(f"❌ Error: Config file not found at {filepath}")
        sys.exit(1)
    return config

config = load_config(CONFIG_FILE)

BASE_URL = config.get("BASE_URL")
if not BASE_URL:
    print("❌ Error: BASE_URL not found in config")
    sys.exit(1)

INPUT_FILE = "926page_source.html"
OUTPUT_FILE = "map4.json"

def normalize_m3u8_url(url):
    try:
        parsed = urlparse(url.lower())
        qs = parse_qs(parsed.query)
        for param in ['txsecret', 'txtime', '_']:
            qs.pop(param, None)
        new_query = urlencode(qs, doseq=True)
        path = parsed.path.rstrip('/')
        return urlunparse(parsed._replace(path=path, query=new_query)).strip()
    except Exception as e:
        print(f"⚠️ Error normalizing URL {url}: {str(e)}")
        return url

# Load HTML berisi daftar live
try:
    with open(INPUT_FILE, encoding="utf-8") as f:
        html = f.read()
except FileNotFoundError:
    print(f"❌ Error: Input file {INPUT_FILE} not found")
    sys.exit(1)

soup = BeautifulSoup(html, "html.parser")
live_ids = [a["href"].split("/")[-1] for a in soup.find_all("a", href=True) if a["href"].startswith("/bofang/")]

print(f"Found {len(live_ids)} live IDs:", live_ids)

# Setup Chrome options
options = Options()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--mute-audio")

if config.get("USER_AGENT"):
    options.add_argument(f'user-agent={config["USER_AGENT"]}')

# Deteksi binary Chrome
chrome_bin = os.getenv("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium-browser") or shutil.which("chromium")
if not chrome_bin:
    print("❌ Tidak menemukan Chrome/Chromium di sistem.")
    sys.exit(1)

options.binary_location = chrome_bin
print(f"ℹ️ Using Chrome binary at: {options.binary_location}")

# Selenium Wire config
seleniumwire_options = {
    'disable_encoding': True,  # biar tetap bisa capture
}

# Inisialisasi driver dengan cara yang benar (Selenium 4+)
try:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(
        service=service,
        options=options,
        seleniumwire_options=seleniumwire_options
    )
except Exception as e:
    print(f"❌ Failed to initialize WebDriver: {str(e)}")
    sys.exit(1)

previous_url_norm = None
placeholder_active = False
results = {}

try:
    for lid in live_ids:
        url = f"{BASE_URL}/live/{lid}"
        print(f"🎯 Live URL: {url}")

        # Kalau placeholder aktif, hentikan pencarian
        if placeholder_active:
            print("   ⚠️ Placeholder aktif, hentikan pencarian ID berikutnya")
            break

        driver.get("about:blank")
        time.sleep(1)
        try:
            del driver.requests
        except:
            pass

        try:
            driver.get(url)
        except Exception as e:
            print(f"   ❌ Failed to load URL: {e}")
            placeholder_active = True
            break  # langsung keluar

        # Tunggu player element
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "video, iframe, .player, .live-container"))
            )
        except Exception as e:
            print(f"   ⚠️ Timeout waiting for player element: {e}")
            placeholder_active = True
            break  # langsung keluar

        time.sleep(3)

        # Ambil m3u8 dari network request
        try:
            m3u8_links = [
                req.url for req in driver.requests
                if req.response and ".m3u8" in req.url
            ]
        except Exception as e:
            print(f"   ⚠️ Error accessing requests: {e}")
            m3u8_links = []

        # Jika tidak ada, coba regex dari page source
        if not m3u8_links:
            page_html = driver.page_source
            found = re.findall(r"https?://[^\s'\"]+\.m3u8[^\s'\"]*", page_html)
            if found:
                m3u8_links = found

        if not m3u8_links:
            print("   ❌ Tidak ditemukan .m3u8")
            placeholder_active = True
            break  # langsung keluar

        final_link = m3u8_links[-1]
        final_link_norm = normalize_m3u8_url(final_link)

        if previous_url_norm == final_link_norm:
            print("   ⚠️ URL sama dengan sebelumnya, aktifkan placeholder dan hentikan pencarian")
            placeholder_active = True
            break  # langsung keluar

        print(f"   ✅ Found .m3u8: {final_link}")
        results[lid] = final_link.strip()
        previous_url_norm = final_link_norm

except Exception as e:
    print(f"❌ Unexpected error: {e}")
finally:
    try:
        driver.quit()
    except:
        pass
        
print("\n📦 Ringkasan hasil:")
for lid, link in results.items():
    print(f"{lid}: {link}")

try:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Hasil disimpan ke {OUTPUT_FILE}")
except Exception as e:
    print(f"❌ Failed to save results: {str(e)}")
