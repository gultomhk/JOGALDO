import os
import asyncio
import requests
import json
import time
import datetime
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import shutil
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

def extract_m3u8(embed_url, wait_time=15):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = None
    m3u8_url = None

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)

        try:
            WebDriverWait(driver, wait_time).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            print("⚠️ Timeout, halaman belum full load")

        driver.execute_script("window.scrollTo(0, 500)")
        time.sleep(5)  # kasih waktu lebih

        # klik play kalau ada
        try:
            play_buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Play') or contains(@class, 'play')]")
            if play_buttons:
                play_buttons[0].click()
                print("▶️ Klik play button")
                time.sleep(5)
        except Exception:
            pass

        # --- Cara 1: log dari devtools
        all_logs = []
        for _ in range(5):
            try:
                all_logs.extend(driver.get_log("performance"))
            except Exception:
                break
            time.sleep(2)

        found_urls = []
        for entry in all_logs:
            try:
                msg = json.loads(entry["message"])
                url = (
                    msg.get("message", {})
                    .get("params", {})
                    .get("request", {})
                    .get("url", "")
                ) or (
                    msg.get("message", {})
                    .get("params", {})
                    .get("response", {})
                    .get("url", "")
                )
                if url and ".m3u8" in url:
                    if not any(k in url.lower() for k in ["ad", "analytics", "track"]):
                        found_urls.append(url)
            except Exception:
                continue

        # --- Cara 2: cek via window.performance
        if not found_urls:
            perf_entries = driver.execute_script("return performance.getEntries();")
            for e in perf_entries:
                url = e.get("name", "")
                if ".m3u8" in url and not any(k in url.lower() for k in ["ad", "analytics", "track"]):
                    found_urls.append(url)

        # simpan raw log buat debug
        with open("raw_logs.json", "w", encoding="utf-8") as f:
            json.dump(all_logs, f, indent=2)

        if found_urls:
            print("🎯 Ketemu kandidat stream:")
            for u in found_urls:
                print("   ", u)
            m3u8_url = found_urls[0]
        else:
            print("❌ Tidak ketemu .m3u8 di log/performance")

    except Exception as e:
        print(f"❌ Error extract_m3u8: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return m3u8_url

async def main(limit_matches=15, apply_time_filter=True):
    res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
    matches = res.json()

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))

    results = {}
    embed_tasks = {}

    # --- Filter matches sesuai waktu & kategori ---
    matches_to_process = []
    for match in matches:
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

    # Step 1: parallel fetch stream metadata
    with ThreadPoolExecutor(max_workers=10) as executor:
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

    # Step 3: extract m3u8 pakai Selenium (jalan blocking di threadpool biar async aman)
    with ThreadPoolExecutor(max_workers=2) as executor:
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

    # simpan hasil ke map5.json
    with open("map5.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Disimpan {len(results)} stream ke map5.json")


if __name__ == "__main__":
    asyncio.run(main())
