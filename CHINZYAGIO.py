import asyncio
import re
from urllib.parse import urlparse
from playwright.async_api import async_playwright
import aiohttp
import requests
from bs4 import BeautifulSoup
import json
import ssl
from pathlib import Path
from datetime import datetime

# ==========================
# KONFIGURASI
# ==========================
CHINZYAIGODATA_FILE = Path.home() / "chinzyaigodata_file.txt"
config_vars = {}
with open(CHINZYAIGODATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL")
CF_CLEARANCE = config_vars.get("CF_CLEARANCE")

OUTPUT_FILE = "map6.json"
TABS = ["football", "basketball", "volleyball", "badminton", "tennis"]

sslcontext = ssl.create_default_context()
sslcontext.check_hostname = False
sslcontext.verify_mode = ssl.CERT_NONE

COMMON_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "id,en-US;q=0.9,en;q=0.8,vi;q=0.7",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}

# Headers dipakai untuk Playwright
EXTRA_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "id,en-US;q=0.9,en;q=0.8,vi;q=0.7",
    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": COMMON_HEADERS["user-agent"],
}

# ===============================================
# FUNGSI ASLI PLAYWRIGHT (tidak diubah struktur)
# ===============================================
async def playwright_fetch_stream(page_url: str, headless=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent=EXTRA_HEADERS["user-agent"],
            viewport={"width": 1280, "height": 800},
        )
        await context.set_extra_http_headers(EXTRA_HEADERS)

        # *** Tambahan: Set cookie CF_Clearance ke domain utama ***
        parsed_base = urlparse(BASE_URL)
        await context.add_cookies([
            {
                "name": "cf_clearance",
                "value": CF_CLEARANCE,
                "domain": parsed_base.hostname,
                "path": "/",
                "secure": True,
            }
        ])

        page = await context.new_page()
        await page.goto(page_url, timeout=60000)
        await asyncio.sleep(2)

        iframe = await page.query_selector("iframe#iframe-stream") or await page.query_selector("iframe")
        if not iframe:
            await browser.close()
            return None

        iframe_src = await iframe.get_attribute("src")
        if not iframe_src:
            await browser.close()
            return None

        parsed = urlparse(iframe_src)
        if parsed.hostname:
            await context.add_cookies([
                {
                    "name": "cf_clearance",
                    "value": CF_CLEARANCE,
                    "domain": parsed.hostname,
                    "path": "/",
                    "secure": True,
                }
            ])

        iframe_page = await context.new_page()
        await iframe_page.set_extra_http_headers({**EXTRA_HEADERS, "referer": page_url})
        await iframe_page.goto(iframe_src, timeout=60000, wait_until="networkidle")

        html = await iframe_page.content()

        # Cari var urlStream
        m = re.search(r'var\s+urlStream\s*=\s*"([^"]+)"', html)
        if m:
            stream_url = m.group(1).replace("\\/", "/")
            if stream_url.startswith("https://live3.procdnlive.com/"):
                stream_url = stream_url.replace("https://", "http://")
            await browser.close()
            return stream_url

        # Cari .m3u8 atau .flv direct
        m2 = re.search(r'https?://[^"\']+\.(m3u8|flv)', html)
        if m2:
            stream_url = m2.group(0)
            if stream_url.startswith("https://live3.procdnlive.com/"):
                stream_url = stream_url.replace("https://", "http://")
            await browser.close()
            return stream_url

        await browser.close()
        return None


# =============== PARSER SLUGS =================
def parse_time_from_slug(slug: str):
    match = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if match:
        h, m, d, mo, y = match.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{m}"
    return "??/??-??.??"


def parse_datetime_key(slug: str):
    match = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if match:
        h, m, d, mo, y = map(int, match.groups())
        try:
            return datetime(y, mo, d, h, m)
        except ValueError:
            return datetime.min
    return datetime.min


def parse_title_from_slug(slug: str):
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    return title_part

# ==========================
# Ambil semua slug
# ==========================
def get_all_slugs():
    print("🌐 Mengambil halaman utama untuk parse semua slug...")
    resp = requests.get(BASE_URL, headers=COMMON_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for tab in TABS:
        tab_section = soup.select_one(f"#{tab}")
        if not tab_section:
            continue
        found = []
        for a in tab_section.select("a[href*='/truc-tiep/']"):
            href = a.get("href", "")
            if not href:
                continue
            slug = re.sub(r"^/|/$", "", href)
            if slug not in found:
                found.append(slug)
        print(f"✅ {tab}: ditemukan {len(found)} slug")
        results.extend(found)

    results = sorted(results, key=parse_datetime_key, reverse=True)
    print(f"📦 Total slug: {len(results)}")
    return results

# ==========================
# Ambil STREAM URL via PLAYWRIGHT
# ==========================
async def fetch_stream_url(session, slug, retries=2):
    full_url = f"{BASE_URL}/{slug}".rstrip("/")

    for attempt in range(1, retries + 1):
        try:
            print(f"🌐 Playwright: {slug} (percobaan {attempt})")

            stream_url = await asyncio.wait_for(
                playwright_fetch_stream(full_url),
                timeout=90
            )

            if stream_url:
                print(f"🎯 {slug} → {stream_url}")
                return slug, stream_url

            print(f"⚠️ Tidak menemukan stream pada {slug}")

        except Exception as e:
            print(f"❌ Error Playwright {slug}: {e}")

        await asyncio.sleep(1)

    return slug, ""

# ==========================
# MAIN
# ==========================
async def main():
    slugs = get_all_slugs()
    print(f"\n🕐 Mulai proses {len(slugs)} slug...\n")

    new_results = {}

    async with aiohttp.ClientSession(headers=COMMON_HEADERS) as session:
        for slug in slugs:
            s, url = await fetch_stream_url(session, slug)
            if url:
                new_results[s] = url
                print(f"💾 [{parse_time_from_slug(s)}] {parse_title_from_slug(s)}")
            else:
                print(f"⏭️ Lewati {s} (tidak ada stream valid)")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_results, f, indent=2, ensure_ascii=False)

    print("\n✅ map6.json berhasil di-rewrite total setelah sukses run.")

if __name__ == "__main__":
    asyncio.run(main())
