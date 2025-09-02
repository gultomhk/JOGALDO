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

    async def process_page(url, wait_ms=8000, label="server"):
        """Buka 1 URL, ambil semua tombol server via data-link, listen response .m3u8"""
        page = await context.new_page()
        collected = []

        # listener global untuk sniff m3u8
        def handle_response(response):
            resp_url = response.url
            if ".m3u8" in resp_url:
                if not any(bad in resp_url for bad in ["404", "google.com", "adexchangeclear"]):
                    if resp_url not in collected:
                        logger.info(f"{label}: m3u8 terdeteksi {resp_url}")
                        collected.append(resp_url)

        page.on("response", handle_response)

        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            logger.info(f"Berhasil membuka halaman: {url}")

            # ambil semua tombol server
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

                    # Klik tombol server untuk memicu permintaan m3u8
                    await btn.click()
                    await page.wait_for_timeout(2000)  # Tunggu sebentar setelah klik

                    # Tunggu response m3u8 setelah klik
                    try:
                        async with page.expect_response(lambda r: ".m3u8" in r.url, timeout=wait_ms) as resp_info:
                            await page.wait_for_timeout(1000)
                        resp = await resp_info.value
                        m3u8_url = resp.url
                        if m3u8_url not in collected:
                            logger.info(f"{label} tombol{idx}: tokenized {m3u8_url}")
                            collected.append(m3u8_url)
                    except Exception as e:
                        logger.warning(f"{label} tombol{idx}: tidak ada response m3u8 setelah klik: {e}")

                except Exception as e:
                    logger.error(f"Gagal proses {label} tombol{idx}: {e}")

            await page.wait_for_timeout(2000)

        except Exception as e:
            logger.error(f"Error buka {label} {url}: {e}")
        finally:
            await page.close()

        return collected

    servers = []
    main_url = f"{BASE_URL}/match/{slug}"
    logger.info(f"Memproses slug: {slug}")

    # 🔹 proses halaman utama (klik tombol → ambil m3u8)
    try:
        main_links = await process_page(main_url, wait_ms=8000, label="main")
        servers.extend(main_links)
        logger.info(f"Slug {slug}: {len(main_links)} link ditemukan dari halaman utama")
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
                links = await process_page(iframe_src, wait_ms=10000, label=f"iframe{idx}")
                servers.extend(links)
                logger.info(f"Slug {slug} iframe{idx}: {len(links)} link ditemukan")
            except Exception as e:
                logger.error(f"Error iframe {idx} slug {slug}: {e}")
        await page.close()
    except Exception as e:
        logger.error(f"Error iframe main page slug {slug}: {e}")

    # 🔹 hapus duplikat tapi jaga urutan
    seen, unique = set(), []
    for link in servers:
        if link not in seen:
            unique.append(link)
            seen.add(link)

    logger.info(f"Slug {slug} selesai: {len(unique)} unique link ditemukan")
    return slug, unique
	
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
            slug, urls = slug_result
            if urls:
                all_data[slug] = urls[0]
                logger.info(f"M3U8 ditemukan (server1): {urls[0]}")
                for i, url in enumerate(urls[1:], start=2):
                    key = f"{slug}server{i}"
                    all_data[key] = url
                    logger.info(f"M3U8 ditemukan (server{i}): {url}")
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
