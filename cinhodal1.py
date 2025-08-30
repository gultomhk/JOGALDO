import os
import asyncio
import requests
import json
import time
import datetime
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Path ke file config
CONFIG_FILE = Path.home() / "sterame3data_file.txt"

# --- Load konfigurasi dari file ---
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

# Assign variabel dari config
MATCHES_URL = config_globals.get("MATCHES_URL")
STREAM_URL = config_globals.get("STREAM_URL")
HEADERS = config_globals.get("HEADERS")

EXEMPT_CATEGORIES = [
    "fight",
    "motor-sports",
    "tennis"
]

def fetch_stream(source_type, source_id):
    """Panggil API stream (blocking, jalan di threadpool)."""
    try:
        url = STREAM_URL.format(source_type, source_id)
        res = requests.get(url, headers=HEADERS, timeout=30)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"⚠️ gagal fetch stream {source_type}/{source_id}: {e}")
        return []

def extract_m3u8(embed_url, wait_time=30):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--remote-debugging-port=0")  # Gunakan port 0 untuk auto-assign
    chrome_options.add_argument("--no-zygote")
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    
    # User agent
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 🔒 disable WebRTC / STUN
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
    chrome_options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    # Experimental options untuk stability
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    m3u8_url = None
    driver = None
    
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service
        
        # Gunakan service dengan timeout yang lebih panjang
        service = Service(
            ChromeDriverManager().install(),
            log_path=os.devnull  # Suppress driver logs
        )
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Set page load timeout
        driver.set_page_load_timeout(45)
        driver.implicitly_wait(10)
        
        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)
        
        # Gunakan WebDriverWait instead of time.sleep
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        
        try:
            # Tunggu sampai halaman loading selesai
            WebDriverWait(driver, wait_time).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            print("⚠️ Page load timeout, continuing with logs...")
        
        # Ambil logs dengan retry mechanism
        logs = []
        retries = 3
        for i in range(retries):
            try:
                logs = driver.get_log("performance")
                if logs:
                    break
                time.sleep(2)  # Tunggu sebentar sebelum retry
            except Exception as e:
                print(f"⚠️ Error getting logs (attempt {i+1}/{retries}): {e}")
                time.sleep(2)
        
        if not logs:
            print("❌ Tidak bisa mendapatkan performance logs")
            return None

        for entry in logs:
            try:
                msg = json.loads(entry["message"])
                message_type = msg.get("message", {}).get("method", "")
                
                if "Network.request" in message_type or "Network.response" in message_type:
                    params = msg.get("message", {}).get("params", {})
                    request_info = params.get("request", {}) or params.get("response", {})
                    url = request_info.get("url", "")
                    
                    if url and ".m3u8" in url:
                        print(f"🎯 ketemu m3u8: {url}")
                        m3u8_url = url
                        break
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass  # Ignore errors during quit

    return m3u8_url


def extract_m3u8_with_retry(embed_url, max_retries=2, wait_time=25):
    """Extract m3u8 dengan mekanisme retry"""
    for attempt in range(max_retries):
        try:
            print(f"🔁 Attempt {attempt + 1}/{max_retries} untuk {embed_url}")
            result = extract_m3u8(embed_url, wait_time)
            if result:
                return result
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed: {e}")
            time.sleep(3)  # Tunggu sebentar sebelum retry
    
    print(f"❌ Gagal setelah {max_retries} attempts untuk {embed_url}")
    return None

async def main(limit_matches=8, apply_time_filter=True):
    try:
        res = requests.get(MATCHES_URL, headers=HEADERS, timeout=20)
        matches = res.json()
    except Exception as e:
        print(f"❌ Gagal mengambil matches: {e}")
        # Buat file kosong sebagai fallback
        with open("map5.json", "w", encoding="utf-8") as f:
            json.dump({}, f)
        return

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))
    results = {}
    embed_tasks = {}

    # --- Filter matches ---
    matches_to_process = []
    for match in matches[:limit_matches]:  # Batasi dari awal
        try:
            # PERBAIKAN: Gunakan start_at bukan startat
            start_at = match["date"] / 1000
            event_time_utc = datetime.datetime.fromtimestamp(start_at, ZoneInfo("UTC"))  # Perbaikan di sini
            event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

            category = match.get("category", "").lower()
            if apply_time_filter and category not in EXEMPT_CATEGORIES:
                if event_time_local < (now - datetime.timedelta(hours=2)):
                    continue

            matches_to_process.append(match)
        except Exception as e:
            print(f"⚠️ Error processing match: {e}")
            continue

    # Step 1: Fetch stream metadata
    with ThreadPoolExecutor(max_workers=3) as executor:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, fetch_stream, src["source"], src["id"])
            for match in matches_to_process
            for src in match.get("sources", [])
        ]
        streams_list = await asyncio.gather(*tasks)

    # Step 2: Process API results
    sources_flat = [src for m in matches_to_process for src in m.get("sources", [])]
    for match_src, streams in zip(sources_flat, streams_list):
        if not streams:
            continue

        stream = streams[0]
        stream_no = stream.get("streamNo", 1)
        key = f"{match_src['source']}/{match_src['id']}/{stream_no}"
        
        url = stream.get("file") or stream.get("url")
        if url:
            results[key] = url
            print(f"[+] API {key} → {url}")
        else:
            embed = stream.get("embedUrl")
            if embed:
                embed_tasks[key] = embed

    # Step 3: Process embed URLs dengan sequential processing
    if embed_tasks:
        print(f"🔄 Memproses {len(embed_tasks)} embed URLs...")
        
        # Process secara sequential untuk menghindari overload
        for key, embed_url in embed_tasks.items():
            print(f"🔍 Processing {key}...")
            m3u8_url = extract_m3u8_with_retry(embed_url)
            if m3u8_url:
                results[key] = m3u8_url
                print(f"[+] Embed {key} → {m3u8_url}")
            else:
                print(f"❌ Gagal extract m3u8 untuk {key}")
            
            # Beri jeda antara requests
            time.sleep(2)

    # Save results
    with open("map5.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Disimpan {len(results)} stream ke map5.json")


if __name__ == "__main__":
    try:
        # Timeout overall execution setelah 15 menit
        asyncio.run(asyncio.wait_for(main(limit_matches=6), timeout=900))
    except asyncio.TimeoutError:
        print("❌ Timeout setelah 15 menit")
        # Tetap simpan hasil yang ada
        with open("map5.json", "w", encoding="utf-8") as f:
            json.dump({}, f)
    except Exception as e:
        print(f"❌ Error utama: {e}")
        with open("map5.json", "w", encoding="utf-8") as f:
            json.dump({}, f)
