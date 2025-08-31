import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin
from playwright.async_api import async_playwright

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

# ========= Parser player?link= → m3u8 =========
def parse_player_link(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    if "link" not in qs:
        return url  # bukan format player

    raw_link = qs["link"][0]
    decoded = unquote(raw_link)

    # tambahkan query tambahan selain 'link'
    extras = []
    for k, v in qs.items():
        if k != "link":
            for item in v:
                extras.append(f"{k}={item}")
    if extras:
        if "?" in decoded:
            decoded += "&" + "&".join(extras)
        else:
            decoded += "?" + "&".join(extras)

    return decoded

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
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            # cek waktu match
            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            # cek live
            is_live = row.select_one(".live-text") is not None

            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Playwright fetch m3u8 per slug =========
def clean_m3u8_links(urls):
    cleaned = []
    for u in set(urls):
        if "player?link=" in u:
            u = parse_player_link(u)
        if ".m3u8" in u:
            cleaned.append(u)
    return cleaned


async def fetch_m3u8_with_playwright(context, slug):
    page = await context.new_page()
    m3u8_links = []

    def handle_request(request):
        if ".m3u8" in request.url or "player?link=" in request.url:
            m3u8_links.append(request.url)

    page.on("request", handle_request)

    try:
        await page.goto(f"{BASE_URL}/match/{slug}", timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        if m3u8_links:
            await page.close()
            return slug, clean_m3u8_links(m3u8_links)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.select_one("iframe[src*='player?link=']")
        if iframe:
            src = urljoin(BASE_URL, iframe["src"])
            iframe_page = await context.new_page()
            iframe_page.on("request", handle_request)
            try:
                await iframe_page.goto(src, timeout=30000, wait_until="domcontentloaded")
                await iframe_page.wait_for_timeout(5000)
                if not m3u8_links:
                    m3u8_links.append(parse_player_link(src))
            finally:
                await iframe_page.close()
    finally:
        await page.close()

    return slug, clean_m3u8_links(m3u8_links)

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        # batasi concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_with_playwright(context, slug)

        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        await browser.close()

        all_data = {}
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Error di task: {result}")
                continue
            slug, urls = result
            if urls:
                if len(urls) == 1:
                    all_data[slug] = urls[0]
                else:
                    all_data[slug] = urls[0]
                    for i, url in enumerate(urls[1:], start=2):
                        key = f"{slug}server{i}"
                        all_data[key] = url
        return all_data

# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8))
    save_map_file(all_data)
