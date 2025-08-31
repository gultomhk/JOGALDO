import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin
import urllib.parse
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

# ========= Playwright fetch m3u8 =========
async def fetch_m3u8_with_playwright(slug):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        m3u8_links = []

        def handle_request(request):
            if ".m3u8" in request.url:
                print(f"   🎯 Ketangkap: {request.url}")
                m3u8_links.append(request.url)

        page.on("request", handle_request)

        try:
            await page.goto(f"{BASE_URL}/match/{slug}", timeout=25000)
            await page.wait_for_timeout(6000)  # tunggu JS jalan
        except Exception as e:
            print(f"   ❌ Error buka {slug}: {e}")

        await browser.close()
        return list(set(m3u8_links))

# ========= Simpan ke MAP pakai Playwright =========
async def save_to_map(slugs):
    new_data = {}

    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{len(slugs)}] ▶ Scraping slug: {slug}", flush=True)
        try:
            m3u8_urls = await fetch_m3u8_with_playwright(slug)

            if m3u8_urls:
                if len(m3u8_urls) == 1:
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 ditemukan: {m3u8_urls[0]}", flush=True)
                else:
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 server1: {m3u8_urls[0]}", flush=True)
                    for i, url in enumerate(m3u8_urls[1:], start=2):
                        key = f"{slug}server{i}"
                        new_data[key] = url
                        print(f"   ✅ M3U8 server{i}: {url}", flush=True)
            else:
                print(f"   ⚠️ Tidak ditemukan .m3u8 di {slug}", flush=True)

        except Exception as e:
            print(f"   ❌ Error slug '{slug}': {e}", flush=True)

    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)

    print(f"✅ map2.json berhasil disimpan! Total entri: {len(new_data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    asyncio.run(save_to_map(slug_list))
