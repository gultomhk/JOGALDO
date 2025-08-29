import os
import asyncio
import requests
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
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

def extract_m3u8(embed_url, wait_time=15):
    chrome_options = Options()

    # ⚙️ Setup Chrome agar stabil di GitHub Actions
    chrome_options.add_argument("--headless=new")   # kalau error, ganti ke --headless=old
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--window-size=1920,1080")

    # 🔒 Disable WebRTC / STUN (biar ga leak IP asli)
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
    chrome_options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

    # 🎭 Fake User-Agent (biar ga dianggap bot)
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # 📊 Logging untuk tangkap request .m3u8
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = None
    m3u8_url = None

    try:
        driver = webdriver.Chrome(options=chrome_options)
        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)

        # ⏳ Tunggu halaman benar-benar load (maks 15 detik)
        try:
            WebDriverWait(driver, wait_time).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            print("⚠️ Timeout, halaman belum full load")

        # 🔄 Scroll supaya iframe/JS ter-trigger
        driver.execute_script("window.scrollTo(0, 500)")
        time.sleep(2)

        # ▶️ Klik tombol "play" kalau ada
        try:
            play_buttons = driver.find_elements(
                By.XPATH, "//button[contains(., 'Play') or contains(@class, 'play')]"
            )
            if play_buttons:
                play_buttons[0].click()
                print("▶️ Klik play button")
                time.sleep(3)
        except Exception:
            pass

        # 📡 Ambil log beberapa kali (karena stream suka delay muncul)
        all_logs = []
        for _ in range(3):
            try:
                all_logs.extend(driver.get_log("performance"))
            except Exception:
                break
            time.sleep(2)

        # Limit supaya log gak kebanyakan
        all_logs = all_logs[-1000:]

        # 🔍 Cari link m3u8
        found_urls = []
        for entry in all_logs:
            try:
                msg = json.loads(entry["message"])
                method = msg.get("message", {}).get("method", "")
                if "Network." not in method:
                    continue

                params = msg.get("message", {}).get("params", {})
                request = params.get("request", {})
                response = params.get("response", {})
                url = request.get("url", "") or response.get("url", "")

                if url and ".m3u8" in url:
                    # 🚫 Skip ads/analytics
                    bad_kw = ["ad", "analytics", "track", "pixel", "google", "doubleclick", "facebook"]
                    if not any(k in url.lower() for k in bad_kw):
                        found_urls.append(url)
                        print(f"🎯 Potensial stream: {url}")
            except Exception:
                continue

        # 🎯 Ambil stream utama
        if found_urls:
            m3u8_url = next(
                (u for u in found_urls if any(k in u for k in ["stream", "live", "hls"])),
                found_urls[0]
            )

    except Exception as e:
        print(f"❌ Error extract_m3u8: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

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
