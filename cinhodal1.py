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
    chrome_options.add_argument("--remote-debugging-port=0")
    
    # User agent yang lebih realistic
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Bypass automation detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    m3u8_url = None
    driver = None
    
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Execute JavaScript untuk bypass detection
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        print(f"\n🌐 buka {embed_url}")
        driver.get(embed_url)
        
        # Tunggu dan coba beberapa metode ekstraksi
        time.sleep(wait_time)
        
        # Method 1: Cari m3u8 di page source
        page_source = driver.page_source
        if ".m3u8" in page_source:
            import re
            m3u8_matches = re.findall(r'https?://[^\s<>"]+\.m3u8[^\s<>"]*', page_source)
            if m3u8_matches:
                m3u8_url = m3u8_matches[0]
                print(f"🎯 ketemu m3u8 di source: {m3u8_url}")
                return m3u8_url
        
        # Method 2: Execute JavaScript untuk mencari video elements
        try:
            video_sources = driver.execute_script("""
                var sources = [];
                // Cari semua video elements
                var videos = document.querySelectorAll('video');
                videos.forEach(function(video) {
                    if (video.src && video.src.includes('.m3u8')) {
                        sources.push(video.src);
                    }
                    // Cari source elements di dalam video
                    var sourceElements = video.querySelectorAll('source');
                    sourceElements.forEach(function(source) {
                        if (source.src && source.src.includes('.m3u8')) {
                            sources.push(source.src);
                        }
                    });
                });
                
                // Cari di JavaScript variables
                var scripts = document.querySelectorAll('script');
                scripts.forEach(function(script) {
                    var scriptText = script.innerHTML;
                    var m3u8Matches = scriptText.match(/'https?[^']+\.m3u8[^']*'/g) || 
                                      scriptText.match(/"https?[^"]+\.m3u8[^"]*"/g);
                    if (m3u8Matches) {
                        m3u8Matches.forEach(function(match) {
                            sources.push(match.replace(/['"]/g, ''));
                        });
                    }
                });
                
                return sources.length > 0 ? sources[0] : null;
            """)
            
            if video_sources:
                print(f"🎯 ketemu m3u8 via JavaScript: {video_sources}")
                return video_sources
                
        except Exception as js_error:
            print(f"⚠️ JavaScript execution error: {js_error}")
        
        # Method 3: Traditional performance logs (fallback)
        try:
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    msg = json.loads(entry["message"])
                    params = msg.get("message", {}).get("params", {})
                    request_info = params.get("request", {}) or params.get("response", {})
                    url = request_info.get("url", "")
                    
                    if url and ".m3u8" in url:
                        print(f"🎯 ketemu m3u8 di logs: {url}")
                        return url
                except:
                    continue
                    
        except Exception as log_error:
            print(f"⚠️ Log access error: {log_error}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return None


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
