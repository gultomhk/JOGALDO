import os
import asyncio
import requests
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
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

def extract_m3u8(embed_url, wait_time=10):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--headless=new")

    # 🔒 disable WebRTC / STUN (biar gak spam error twilio stun)
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
    chrome_options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    # cukup set capability logging
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(options=chrome_options)
    m3u8_url = None
    try:
        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)
        time.sleep(wait_time)

        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])
                params = msg.get("message", {}).get("params", {})
                url = params.get("request", {}).get("url", "")
                if ".m3u8" in url:
                    print(f"🎯 ketemu m3u8: {url}")
                    m3u8_url = url
                    break
            except Exception:
                continue
    finally:
        driver.quit()

    return m3u8_url


async def main(limit_matches=15):
    res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
    matches = res.json()

    results = {}
    embed_tasks = {}

    # Step 1: parallel fetch stream metadata
    with ThreadPoolExecutor(max_workers=10) as executor:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, fetch_stream, src["source"], src["id"])
            for match in matches[:limit_matches]
            for src in match.get("sources", [])
        ]
        streams_list = await asyncio.gather(*tasks)

    # Step 2: proses hasil API
    found = 0
    for (match, streams) in zip(
        [src for m in matches[:limit_matches] for src in m.get("sources", [])],
        streams_list,
    ):
        source_type, source_id = match["source"], match["id"]
        for stream in streams:
            stream_no = stream.get("streamNo", 1)
            key = f"{source_type}/{source_id}/{stream_no}"

            url = stream.get("file") or stream.get("url")
            if url:
                results[key] = url
                found += 1
                print(f"[+] API {key} → {url}")
            else:
                embed = stream.get("embedUrl")
                if embed:
                    embed_tasks[key] = embed

            if found >= limit_matches:
                break

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
