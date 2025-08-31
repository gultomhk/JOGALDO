import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import datetime
from zoneinfo import ZoneInfo
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
PROXY_LIST_URL = config_globals.get("PROXY_LIST_URL")

EXEMPT_CATEGORIES = ["fight", "motor-sports", "tennis"]

# --------------- Utils -----------------

def load_proxies():
    """Ambil list proxy dari GitHub"""
    try:
        resp = requests.get(PROXY_LIST_URL, timeout=15)
        resp.raise_for_status()
        proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
        print(f"🔌 Total proxy terambil: {len(proxies)}")
        return proxies
    except Exception as e:
        print(f"⚠️ Gagal ambil proxy list: {e}")
        return []


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


def extract_m3u8(embed_url, wait_time=15, proxy=None):
    """Buka embed_url pakai Selenium + proxy, cari .m3u8"""
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--headless=new")

    # set proxy jika ada
    if proxy:
        if proxy.startswith("http") or proxy.startswith("socks"):
            chrome_options.add_argument(f"--proxy-server={proxy}")
        else:
            chrome_options.add_argument(f"--proxy-server=http://{proxy}")
        print(f"🌍 pakai proxy: {proxy}")

    # disable WebRTC / STUN
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
    chrome_options.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

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


def find_working_proxy(embed_url, proxies):
    """Cari 1 proxy yang sukses buka embed_url"""
    for proxy in proxies:
        print(f"🔎 coba proxy {proxy}")
        try:
            url = extract_m3u8(embed_url, wait_time=10, proxy=proxy)
            if url:
                print(f"✅ Proxy OK: {proxy}")
                return proxy
        except Exception as e:
            print(f"❌ proxy {proxy} error: {e}")
    print("⚠️ Tidak ada proxy yang berhasil")
    return None

# --------------- Main Logic -----------------

async def main(limit_matches=20, apply_time_filter=True):
    res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
    matches = res.json()

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))

    # --- Filter matches sesuai waktu & kategori ---
    filtered_matches = []
    for match in matches:
        start_at = match["date"] / 1000
        event_time_utc = datetime.datetime.fromtimestamp(start_at, ZoneInfo("UTC"))
        event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

        category = match.get("category", "").lower()
        if apply_time_filter and category not in EXEMPT_CATEGORIES:
            if event_time_local < (now - datetime.timedelta(hours=2)):
                continue
        filtered_matches.append(match)

    print(f"📊 Total match terpilih: {len(filtered_matches)}")

    results = {}
    embed_tasks = {}

    # Step 1: parallel fetch stream metadata
    with ThreadPoolExecutor(max_workers=10) as executor:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, fetch_stream, src["source"], src["id"])
            for match in filtered_matches[:limit_matches]
            for src in match.get("sources", [])
        ]
        streams_list = await asyncio.gather(*tasks)

    # Step 2: proses hasil API
    for (src, streams) in zip(
        [s for m in filtered_matches[:limit_matches] for s in m.get("sources", [])],
        streams_list,
    ):
        source_type, source_id = src["source"], src["id"]

        if not streams:
            continue

        stream = streams[0]
        stream_no = stream.get("streamNo", 1)

        key = f"{source_type}/{source_id}/{stream_no}"
        url = stream.get("file") or stream.get("url")
        if url:
            results[key] = url
            print(f"[+] API {key} → {url}")
        else:
            embed = stream.get("embedUrl")
            if embed:
                embed_tasks[key] = embed

    # Step 3: tentukan proxy yang valid
    proxies = load_proxies()
    working_proxy = None
    if embed_tasks and proxies:
        test_url = list(embed_tasks.values())[0]
        working_proxy = find_working_proxy(test_url, proxies)

    # Step 4: extract semua embed pakai proxy yang sudah valid
    if working_proxy:
        with ThreadPoolExecutor(max_workers=2) as executor:
            loop = asyncio.get_running_loop()
            tasks = [
                loop.run_in_executor(executor, extract_m3u8, embed_url, 15, working_proxy)
                for embed_url in embed_tasks.values()
            ]
            results_list = await asyncio.gather(*tasks)

        for key, url in zip(embed_tasks.keys(), results_list):
            if url:
                results[key] = url
                print(f"[+] Embed {key} → {url}")

    # Step 5: simpan hasil ke map5.json
    with open("map5.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Disimpan {len(results)} stream ke map5.json")


if __name__ == "__main__":
    asyncio.run(main())
