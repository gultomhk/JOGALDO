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
    chrome_options.add_argument("--disable-dev-shm-usage")  # Penting untuk environment Docker/CI
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--no-zygote")
    chrome_options.add_argument("--single-process")  # Untuk menghemat memory

    # User agent untuk mengurangi deteksi automation
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 🔒 disable WebRTC / STUN
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
    chrome_options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    # cukup set capability logging
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    m3u8_url = None
    driver = None
    
    try:
        # Gunakan ChromeDriverManager untuk mendapatkan driver yang tepat
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)
        time.sleep(wait_time)

        logs = driver.get_log("performance")

        for entry in logs:
            try:
                msg = json.loads(entry["message"])
                message_type = msg.get("message", {}).get("method", "")
                
                # Hanya proses log network requests
                if "Network.request" in message_type or "Network.response" in message_type:
                    params = msg.get("message", {}).get("params", {})
                    request_info = params.get("request", {}) or params.get("response", {})
                    url = request_info.get("url", "")
                    
                    if url and ".m3u8" in url:
                        print(f"🎯 ketemu m3u8: {url}")
                        m3u8_url = url
                        break
            except Exception as e:
                print("⚠️ error parsing log:", e)
                continue
                
    except WebDriverException as e:
        print(f"❌ WebDriver error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        if driver:
            driver.quit()

    return m3u8_url

async def main(limit_matches=10, apply_time_filter=True):  # Kurangi limit matches
    try:
        res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
        matches = res.json()
    except Exception as e:
        print(f"❌ Gagal mengambil matches: {e}")
        return

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))
    results = {}
    embed_tasks = {}

    # --- Filter matches sesuai waktu & kategori ---
    matches_to_process = []
    for match in matches:
        try:
            start_at = match["date"] / 1000
            event_time_utc = datetime.datetime.fromtimestamp(start_at, ZoneInfo("UTC"))
            event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

            category = match.get("category", "").lower()
            if apply_time_filter and category not in EXEMPT_CATEGORIES:
                if event_time_local < (now - datetime.timedelta(hours=2)):
                    continue

            matches_to_process.append(match)
            if len(matches_to_process) >= limit_matches:
                break
        except Exception as e:
            print(f"⚠️ Error processing match: {e}")
            continue

    # Step 1: parallel fetch stream metadata
    with ThreadPoolExecutor(max_workers=5) as executor:  # Kurangi workers
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, fetch_stream, src["source"], src["id"])
            for match in matches_to_process
            for src in match.get("sources", [])
        ]
        streams_list = await asyncio.gather(*tasks)

    # Step 2: proses hasil API, ambil hanya server 1
    sources_flat = [src for m in matches_to_process for src in m.get("sources", [])]
    for match_src, streams in zip(sources_flat, streams_list):
        source_type, source_id = match_src["source"], match_src["id"]

        if not streams:
            continue

        # Ambil hanya server 1
        stream = streams[0]
        stream_no = stream.get("streamNo", 1)
        if stream_no != 1:
            stream_no = 1

        key = f"{source_type}/{source_id}/{stream_no}"
        url = stream.get("file") or stream.get("url")
        if url:
            results[key] = url
            print(f"[+] API {key} → {url}")
        else:
            embed = stream.get("embedUrl")
            if embed:
                embed_tasks[key] = embed

    # Step 3: extract m3u8 pakai Selenium (jalan blocking di threadpool)
    if embed_tasks:
        print(f"🔄 Memproses {len(embed_tasks)} embed URLs...")
        with ThreadPoolExecutor(max_workers=1) as executor:  # Hanya 1 worker untuk Selenium
            loop = asyncio.get_running_loop()
            tasks = [
                loop.run_in_executor(executor, extract_m3u8, embed_url)
                for embed_url in embed_tasks.values()
            ]
            results_list = await asyncio.gather(*tasks)

        for key, url in zip(embed_tasks.keys(), results_list):
            if url:
                results[key] = url
                print(f"[+] Embed {key} → {url}")
            else:
                print(f"❌ Gagal extract m3u8 untuk {key}")

    # simpan hasil ke map5.json
    with open("map5.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Disimpan {len(results)} stream ke map5.json")


if __name__ == "__main__":
    # Timeout untuk mencegah hang selamanya
    try:
        asyncio.run(main(limit_matches=8))  # Lebih sedikit matches
    except Exception as e:
        print(f"❌ Error utama: {e}")
        # Tetap buat file kosong jika error
        with open("map5.json", "w", encoding="utf-8") as f:
            json.dump({}, f)
