import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright
import logging
import time

# ========= Setup Logging =========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("slug_processing.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {CONFIG_FILE}")

config = load_config(CONFIG_FILE)
BASE_URL = config["BASE_URL"]
USER_AGENT = config["USER_AGENT"]
now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========= Parser player?link= → nilai link (ENCODED) + extra params =========
def parse_player_link(url: str, keep_encoded: bool = True) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "link" not in qs:
        return url
    encoded_link_value = qs["link"][0]
    extras = {k: v for k, v in qs.items() if k != "link"}
    extra_str = urlencode(extras, doseq=True) if extras else ""
    if keep_encoded:
        return encoded_link_value + (("&" + extra_str) if extra_str else "")
    else:
        decoded = unquote(encoded_link_value)
        if extra_str:
            decoded += "&" + extra_str if "?" in decoded else "?" + extra_str
        return decoded

# ========= Ekstraksi M3U8 (HTML & iframe) =========
def extract_m3u8_urls(html, base_url=BASE_URL):
    """Ekstrak URL m3u8 dari HTML dengan follow iframe/player untuk ambil authkey"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if not raw:
            continue

        # --- Kasus langsung ---
        if raw.endswith(".m3u8") and raw.startswith("http"):
            logger.info(f"Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)

        # --- Kasus iframe/player ---
        elif "/player?link=" in raw:
            iframe_url = urljoin(base_url, raw)
            logger.info(f"Cek iframe: {iframe_url}")
            try:
                r = requests.get(iframe_url, headers={"User-Agent": USER_AGENT}, timeout=10)
                if r.ok:
                    iframe_html = r.text
                    found = re.findall(r"https?://[^\s\"']+\.m3u8[^\s\"']*", iframe_html)
                    if found:
                        for f in found:
                            if any(k in f for k in ["auth", "token", "key="]):
                                logger.info(f"Dari iframe (authkey): ✅ {f}")
                                m3u8_urls.append(f)
                            else:
                                logger.info(f"Dari iframe tanpa auth: {f}")
                else:
                    logger.error(f"Gagal load iframe: {r.status_code}")
            except Exception as e:
                logger.error(f"Error iframe fetch: {e}")

        else:
            logger.info(f"Skip: {raw}")

    return m3u8_urls

# ========= Ambil daftar slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    return None

def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    logger.info(f"Total match ditemukan: {len(matches)}")
    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz=tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            is_live = row.select_one(".live-text") is not None

            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                logger.info(f"Lewat waktu & bukan live, skip: {slug}")
                continue

            slug_lower = slug.lower()
            is_exception = any(
                keyword in slug_lower
                for keyword in ["tennis", "billiards", "snooker", "worldssp", "superbike"]
            )
            if not is_live and not is_exception and event_time_local < (now - timedelta(hours=hours_threshold)):
                continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            logger.error(f"Gagal parsing row: {e}")
            continue

    logger.info(f"Total slug valid: {len(slugs)}")
    return slugs

# ========= Pembersih hasil URL =========
def clean_m3u8_links(urls, keep_encoded=True):
    cleaned = []
    seen = set()
    for u in urls:
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)
        if (
            ".m3u8" in u
            and "404" not in u
            and "google.com" not in u
            and "adexchangeclear" not in u
            and u not in seen
        ):
            cleaned.append(u)
            seen.add(u)
    return cleaned

# ========= Playwright fetch m3u8 per slug =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    """
    Ambil semua link .m3u8 tokenized dari 1 slug.
    """
    logger.info(f"🚀 Memproses slug: {slug}")
    
    main_url = f"{BASE_URL}/match/{slug}"
    all_server_urls = {}
    
    try:
        # Buka halaman utama
        page = await context.new_page()
        await page.goto(main_url, timeout=30000, wait_until="domcontentloaded")
        logger.info(f"✅ Berhasil membuka halaman utama: {main_url}")
        
        # Tunggu sebentar untuk memastikan halaman terload sempurna
        await page.wait_for_timeout(3000)
        
        # Ambil konten halaman untuk dianalisis
        page_content = await page.content()
        soup = BeautifulSoup(page_content, "html.parser")
        
        # 1. Cari tombol server di halaman utama
        buttons = await page.query_selector_all(".list-server button[data-link], .btn-server[data-link], button[data-link]")
        logger.info(f"🔍 Ditemukan {len(buttons)} tombol server di halaman utama")
        
        if buttons:
            # Proses tombol server yang ditemukan
            for i, btn in enumerate(buttons):
                try:
                    btn_text = await btn.inner_text() or f"server_{i+1}"
                    data_link = await btn.get_attribute("data-link")
                    
                    logger.info(f"🔘 Tombol {i+1}: {btn_text} - {data_link}")
                    
                    # Klik tombol untuk memicu load stream
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    
                    # Cari URL m3u8 setelah klik
                    m3u8_url = await find_m3u8_url(page)
                    
                    if m3u8_url:
                        logger.info(f"✅ {btn_text}: {m3u8_url}")
                        all_server_urls[btn_text] = m3u8_url
                    else:
                        logger.warning(f"⚠️ {btn_text}: Tidak ditemukan URL m3u8")
                        
                except Exception as e:
                    logger.error(f"❌ Error memproses tombol {i+1}: {e}")
        else:
            logger.info("ℹ️ Tidak ditemukan tombol server di halaman utama")
        
        # 2. Cari iframe player (sangat penting!)
        iframes = soup.select("iframe[src]")
        logger.info(f"🔍 Ditemukan {len(iframes)} iframe di halaman")
        
        for i, iframe in enumerate(iframes):
            try:
                iframe_src = iframe.get("src")
                if iframe_src and "player" in iframe_src:
                    full_iframe_url = urljoin(BASE_URL, iframe_src)
                    logger.info(f"🎯 Iframe {i+1}: {full_iframe_url}")
                    
                    # SIMPAN LANGSUNG URL IFRAME SEBAGAI STREAM!
                    # Karena iframe ini sudah mengandung token yang valid
                    all_server_urls[f"iframe_{i+1}"] = full_iframe_url
                    logger.info(f"✅ Menyimpan iframe sebagai stream: {full_iframe_url}")
                    
            except Exception as e:
                logger.error(f"❌ Error memproses iframe {i+1}: {e}")
        
        # 3. Cari langsung elemen video dengan src m3u8
        video_elements = await page.query_selector_all("video, audio")
        for i, elem in enumerate(video_elements):
            try:
                src = await elem.get_attribute("src")
                if src and ".m3u8" in src:
                    logger.info(f"🎯 Video element {i+1}: {src}")
                    all_server_urls[f"video_{i+1}"] = src
            except Exception as e:
                logger.error(f"❌ Error memproses video element {i+1}: {e}")
        
        await page.close()
        
    except Exception as e:
        logger.error(f"❌ Error memproses slug {slug}: {e}")
    
    logger.info(f"✅ Slug {slug} selesai: {len(all_server_urls)} stream ditemukan")
    return slug, all_server_urls

async def find_m3u8_url(page):
    """Cari URL m3u8 di halaman dengan berbagai metode"""
    methods = [
        # Method 1: Cek video elements
        lambda: page.evaluate("""
            () => {
                const videos = document.querySelectorAll('video, audio');
                for (let video of videos) {
                    if (video.src && video.src.includes('.m3u8')) {
                        return video.src;
                    }
                }
                return null;
            }
        """),
        
        # Method 2: Cek iframe sources
        lambda: page.evaluate("""
            () => {
                const iframes = document.querySelectorAll('iframe');
                for (let iframe of iframes) {
                    if (iframe.src && iframe.src.includes('.m3u8')) {
                        return iframe.src;
                    }
                }
                return null;
            }
        """),
        
        # Method 3: Cek JavaScript variables
        lambda: page.evaluate("""
            () => {
                // Cek berbagai object global yang mungkin menyimpan URL
                const objectsToCheck = [window, document, document.body];
                for (let obj of objectsToCheck) {
                    for (let key in obj) {
                        if (typeof obj[key] === 'string' && obj[key].includes('.m3u8')) {
                            return obj[key];
                        }
                    }
                }
                return null;
            }
        """)
    ]
    
    for method in methods:
        try:
            result = await method()
            if result and ".m3u8" in result:
                return result
        except:
            continue
    
    return None

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=3):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-web-security',
                '--allow-running-insecure-content',
            ]
        )
        
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True
        )
        
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_with_playwright(context, slug)

        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

        all_data = {}
        for slug_result in results:
            if isinstance(slug_result, Exception):
                logger.error(f"❌ Error di task: {slug_result}")
                continue
            slug, server_urls = slug_result
            if server_urls:
                for server_name, url in server_urls.items():
                    if "server-1" in server_name.lower() or "server1" in server_name.lower():
                        all_data[slug] = url
                    else:
                        key = f"{slug}_{server_name.replace(' ', '_')}"
                        all_data[key] = url
                    logger.info(f"✅ Stream ditemukan ({server_name}): {url}")
            else:
                logger.warning(f"⚠️ Tidak ditemukan stream pada slug: {slug}")

        return all_data

# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    
    # Test dengan beberapa slug pertama saja
    test_slugs = slug_list[:2] if slug_list else []
    logger.info(f"🧪 Testing dengan {len(test_slugs)} slug: {test_slugs}")
    
    all_data = asyncio.run(fetch_all_parallel(test_slugs, concurrency=2))
    save_map_file(all_data)
