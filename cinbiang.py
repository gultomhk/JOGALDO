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
import json, sys
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
        print(f"❌ Config file not found at {filepath}")
        sys.exit(1)
    return config

config = load_config(CONFIG_FILE)

BASE_URL = config.get("BASE_URL")
if not BASE_URL:
    print("❌ BASE_URL not found in config")
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
        return urlunparse(parsed._replace(path=parsed.path.rstrip('/'), query=new_query)).strip()
    except Exception as e:
        print(f"⚠️ Error normalizing URL {url}: {e}")
        return url

# --- Ambil daftar live IDs dari HTML ---
try:
    with open(INPUT_FILE, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
except FileNotFoundError:
    print(f"❌ Input file {INPUT_FILE} not found")
    sys.exit(1)

live_ids = [a["href"].split("/")[-1] for a in soup.find_all("a", href=True) if a["href"].startswith("/bofang/")]
print(f"Found {len(live_ids)} live IDs:", live_ids)

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
    driver = webdriver.Chrome(service=service, options=options, seleniumwire_options=seleniumwire_options)
except Exception as e:
    print(f"❌ Failed to initialize Chrome WebDriver: {e}")
    sys.exit(1)

previous_url_norm = None
placeholder_active = False
results = {}

try:
    for lid in live_ids:
        url = f"{BASE_URL}/live/{lid}"
        print(f"\n🎯 Checking: {url}")

        if placeholder_active:
            print("   ⚠️ Placeholder active, stopping further checks")
            break

        driver.get("about:blank")
        time.sleep(0.5)
        driver.requests.clear()

        try:
            driver.get(url)
        except Exception as e:
            print(f"   ❌ Page load failed: {e}")
            placeholder_active = True
            break

        # Step 1: Wait for player element
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "video, iframe, .player, .live-container"))
            )
            print("   ℹ️ Player element detected")
        except:
            print("   ⚠️ Player not found in 15s")
            placeholder_active = True
            break

        # Step 2: Poll network requests for m3u8
        m3u8_links = []
        start = time.time()
        while time.time() - start < 15:
            m3u8_links = [req.url for req in driver.requests if req.response and ".m3u8" in req.url]
            if m3u8_links:
                break
            time.sleep(1)

        # Step 3: Fallback regex search
        if not m3u8_links:
            found = re.findall(r"https?://[^\s'\"]+\.m3u8[^\s'\"]*", driver.page_source)
            if found:
                m3u8_links = found

        if not m3u8_links:
            print("   ❌ No m3u8 link found")
            placeholder_active = True
            break

        final_link = m3u8_links[-1]
        final_link_norm = normalize_m3u8_url(final_link)

        if previous_url_norm == final_link_norm:
            print("   ⚠️ Same as previous stream, stopping")
            placeholder_active = True
            break

        print(f"   ✅ Found m3u8: {final_link}")
        results[lid] = final_link.strip()
        previous_url_norm = final_link_norm

finally:
    driver.quit()

# --- Save results ---
print("\n📦 Results:")
for lid, link in results.items():
    print(f"{lid}: {link}")

try:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved to {OUTPUT_FILE}")
except Exception as e:
    print(f"❌ Failed to save: {e}")
