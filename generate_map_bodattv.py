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
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
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

# ========= Playwright fetch m3u8 per slug (FINAL MULTI SERVER, FIXED) =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    """
    Ambil semua link .m3u8 tokenized dari 1 slug.
    Semua tombol server diproses, iframe player otomatis diikuti.
    """

    async def process_server_buttons(page, label="main"):
        """Proses semua tombol server pada halaman dan kembalikan URL m3u8 untuk masing-masing"""
        server_urls = {}
        
        # Ambil semua tombol server
        buttons = await page.query_selector_all(".list-server button[data-link]") or []
        logger.info(f"{label}: {len(buttons)} tombol server ditemukan")
        
        for idx, btn in enumerate(buttons, start=1):
            try:
                name = (await btn.inner_text() or f"server{idx}").strip().replace(" ", "_")
                data_link = await btn.get_attribute("data-link")
                if not data_link:
                    logger.warning(f"{label} tombol{idx} ({name}): tidak ada data-link")
                    continue
                
                logger.info(f"Proses {label} tombol{idx} ({name}) - data-link: {data_link}")
                
                # Buat promise untuk menangkap response m3u8 sebelum klik
                response_promise = asyncio.create_task(
                    wait_for_m3u8_response(page, timeout=10000)
                )
                
                # Klik tombol server
                await btn.click()
                await page.wait_for_timeout(2000)  # Tunggu setelah klik
                
                # Tunggu response m3u8
                try:
                    m3u8_url = await asyncio.wait_for(response_promise, timeout=10)
                    if m3u8_url:
                        server_urls[name] = m3u8_url
                        logger.info(f"{label} {name}: tokenized {m3u8_url}")
                    else:
                        logger.warning(f"{label} {name}: tidak ada response m3u8 setelah klik")
                except asyncio.TimeoutError:
                    logger.warning(f"{label} {name}: timeout menunggu response m3u8")
                
            except Exception as e:
                logger.error(f"Gagal proses {label} tombol{idx}: {e}")
        
        return server_urls
    
    async def wait_for_m3u8_response(page, timeout=10000):
        """Tunggu dan kembalikan URL m3u8 dari response"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Periksa apakah ada elemen video atau iframe yang berubah
            video_elements = await page.query_selector_all("video, iframe")
            for elem in video_elements:
                src = await elem.get_attribute("src")
                if src and ".m3u8" in src:
                    return src
            
            # Tunggu sebentar sebelum pemeriksaan berikutnya
            await asyncio.sleep(0.5)
        
        return None

    async def process_page(url, label="server"):
        """Buka 1 URL dan proses semua tombol server di dalamnya"""
        page = await context.new_page()
        server_urls = {}
        
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            logger.info(f"Berhasil membuka halaman: {url}")
            
            # Proses tombol server
            server_urls = await process_server_buttons(page, label)
            
        except Exception as e:
            logger.error(f"Error buka {label} {url}: {e}")
        finally:
            await page.close()
        
        return server_urls

    all_server_urls = {}
    main_url = f"{BASE_URL}/match/{slug}"
    logger.info(f"Memproses slug: {slug}")

    # 🔹 proses halaman utama (klik tombol → ambil m3u8)
    try:
        main_servers = await process_page(main_url, label="main")
        all_server_urls.update(main_servers)
        logger.info(f"Slug {slug}: {len(main_servers)} server ditemukan dari halaman utama")
    except Exception as e:
        logger.error(f"Error main slug {slug}: {e}")

    # 🔹 proses iframe bawaan (kalau ada)
    try:
        page = await context.new_page()
        await page.goto(main_url, timeout=30000, wait_until="domcontentloaded")

        soup = BeautifulSoup(await page.content(), "html.parser")
        iframes = soup.select("iframe[src*='player?link=']")
        logger.info(f"Slug {slug}: {len(iframes)} iframe ditemukan")
        
        for idx, iframe in enumerate(iframes, start=1):
            iframe_src = urljoin(BASE_URL, iframe["src"])
            logger.info(f"Proses iframe default{idx}: {iframe_src}")
            try:
                iframe_servers = await process_page(iframe_src, label=f"iframe{idx}")
                # Tambahkan prefix untuk membedakan server dari iframe yang berbeda
                prefixed_servers = {f"iframe{idx}_{k}": v for k, v in iframe_servers.items()}
                all_server_urls.update(prefixed_servers)
                logger.info(f"Slug {slug} iframe{idx}: {len(iframe_servers)} server ditemukan")
            except Exception as e:
                logger.error(f"Error iframe {idx} slug {slug}: {e}")
        await page.close()
    except Exception as e:
        logger.error(f"Error iframe main page slug {slug}: {e}")

    logger.info(f"Slug {slug} selesai: {len(all_server_urls)} unique server ditemukan")
    return slug, all_server_urls
	
# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_with_playwright(context, slug, keep_encoded=keep_encoded)

        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

        all_data = {}
        for slug_result in results:
            if isinstance(slug_result, Exception):
                logger.error(f"Error di task: {slug_result}")
                continue
            slug, server_urls = slug_result
            if server_urls:
                for server_name, url in server_urls.items():
                    if server_name == "Server-1":  # Server utama
                        all_data[slug] = url
                    else:
                        key = f"{slug}_{server_name}"
                        all_data[key] = url
                    logger.info(f"M3U8 ditemukan ({server_name}): {url}")
            else:
                logger.warning(f"Tidak ditemukan .m3u8 pada slug: {slug}")

        return all_data

# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"map2.json berhasil disimpan! Total entri: {len(data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)

    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8, keep_encoded=True))
    save_map_file(all_data)
