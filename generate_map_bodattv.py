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

# ========= Playwright fetch m3u8 per slug =========
async def fetch_m3u8_with_playwright(context, slug):
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
        
        # Screenshot untuk debugging
        await page.screenshot(path=f"debug_{slug}.png", full_page=True)
        
        # Periksa struktur halaman
        page_content = await page.content()
        soup = BeautifulSoup(page_content, "html.parser")
        
        # Cek berbagai kemungkinan struktur tombol server
        selectors_to_try = [
            ".list-server button[data-link]",
            ".server-list button[data-link]",
            ".btn-server[data-link]",
            "button[data-link]",
            ".server-option[data-link]",
            "[data-link-type='hls']"
        ]
        
        buttons = []
        for selector in selectors_to_try:
            found_buttons = await page.query_selector_all(selector)
            if found_buttons:
                logger.info(f"🔍 Ditemukan {len(found_buttons)} tombol dengan selector: {selector}")
                buttons.extend(found_buttons)
                break
        
        if not buttons:
            logger.warning(f"❌ Tidak ditemukan tombol server di halaman utama")
            # Coba cari iframe
            iframes = await page.query_selector_all("iframe")
            logger.info(f"🔍 Ditemukan {len(iframes)} iframe")
            
            for i, iframe in enumerate(iframes):
                try:
                    iframe_src = await iframe.get_attribute("src")
                    if iframe_src and "player" in iframe_src:
                        logger.info(f"🔄 Memproses iframe {i+1}: {iframe_src}")
                        
                        # Buka iframe di tab baru
                        iframe_page = await context.new_page()
                        full_iframe_url = urljoin(BASE_URL, iframe_src)
                        await iframe_page.goto(full_iframe_url, timeout=30000, wait_until="domcontentloaded")
                        
                        # Cari tombol di iframe
                        iframe_buttons = await iframe_page.query_selector_all("button[data-link]")
                        if iframe_buttons:
                            logger.info(f"✅ Ditemukan {len(iframe_buttons)} tombol di iframe")
                            buttons.extend(iframe_buttons)
                        
                        await iframe_page.close()
                except Exception as e:
                    logger.error(f"❌ Error memproses iframe {i+1}: {e}")
        
        # Proses tombol yang ditemukan
        if buttons:
            logger.info(f"🎯 Total {len(buttons)} tombol server akan diproses")
            
            for i, btn in enumerate(buttons):
                try:
                    # Dapatkan informasi tombol
                    btn_text = await btn.inner_text() or f"server_{i+1}"
                    data_link = await btn.get_attribute("data-link")
                    data_link_type = await btn.get_attribute("data-link-type") or "unknown"
                    
                    logger.info(f"🔘 Tombol {i+1}: {btn_text} - {data_link_type} - {data_link}")
                    
                    # Klik tombol
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
            logger.warning("⚠️ Tidak ada tombol server yang ditemukan di halaman manapun")
            
        await page.close()
        
    except Exception as e:
        logger.error(f"❌ Error memproses slug {slug}: {e}")
    
    logger.info(f"✅ Slug {slug} selesai: {len(all_server_urls)} server ditemukan")
    return slug, all_server_urls

async def find_m3u8_url(page):
    """Cari URL m3u8 di halaman"""
    # Cek di video elements
    video_elements = await page.query_selector_all("video, audio, iframe")
    for elem in video_elements:
        src = await elem.get_attribute("src")
        if src and ".m3u8" in src:
            return src
    
    # Cek di JavaScript variables (mungkin ada di window atau global vars)
    try:
        js_vars = await page.evaluate("""
            () => {
                const sources = [];
                // Cek window object
                for (let key in window) {
                    if (typeof window[key] === 'string' && window[key].includes('.m3u8')) {
                        sources.push(window[key]);
                    }
                }
                // Cek videojs players
                document.querySelectorAll('video').forEach(video => {
                    if (video.src && video.src.includes('.m3u8')) {
                        sources.push(video.src);
                    }
                });
                return sources;
            }
        """)
        
        for url in js_vars:
            if ".m3u8" in url:
                return url
    except:
        pass
    
    # Monitor network requests terakhir
    try:
        responses = page.context._responses
        for response in list(responses)[-10:]:  # Cek 10 response terakhir
            url = response.url
            if ".m3u8" in url:
                return url
    except:
        pass
    
    return None

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=3):
    async with async_playwright() as p:
        # Launch browser dengan lebih banyak options
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-web-security',
                '--allow-running-insecure-content',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials'
            ]
        )
        
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True
        )
        
        # Enable request interception untuk monitor network
        await context.route("**/*", lambda route: route.continue_())
        
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
                    if server_name.lower() == "server-1" or server_name.lower() == "server1":
                        all_data[slug] = url
                    else:
                        key = f"{slug}_{server_name.replace(' ', '_')}"
                        all_data[key] = url
                    logger.info(f"✅ M3U8 ditemukan ({server_name}): {url}")
            else:
                logger.warning(f"⚠️ Tidak ditemukan .m3u8 pada slug: {slug}")

        return all_data

# ========= Fungsi lainnya tetap sama =========
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
    logger.info(f"📦 Total match ditemukan: {len(matches)}")
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
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            is_live = row.select_one(".live-text") is not None

            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                logger.info(f"⏩ Lewat waktu & bukan live, skip: {slug}")
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
            logger.error(f"❌ Gagal parsing row: {e}")
            continue

    logger.info(f"📦 Total slug valid: {len(slugs)}")
    return slugs

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
    
    # Coba hanya dengan beberapa slug pertama untuk testing
    test_slugs = slug_list[:3] if slug_list else []
    logger.info(f"🧪 Testing dengan {len(test_slugs)} slug: {test_slugs}")
    
    all_data = asyncio.run(fetch_all_parallel(test_slugs, concurrency=2))
    save_map_file(all_data)
