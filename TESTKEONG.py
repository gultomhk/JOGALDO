import asyncio
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from pathlib import Path
from deep_translator import GoogleTranslator
from playwright.async_api import async_playwright

# =====================================================
# KONFIGURASI
# =====================================================
CONFIG_FILE = Path.home() / "keongdata.txt"
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

def clean_value(val):
    if isinstance(val, str):
        return val.strip()
    return val

BASE_URL = clean_value(config_globals.get("BASE_URL"))
TABS = config_globals.get("TABS", [])
USER_AGENT = clean_value(config_globals.get("USER_AGENT"))
REFERRER = clean_value(config_globals.get("REFERRER"))
LOGO_URL = clean_value(config_globals.get("LOGO_URL"))
MY_WEBSITE = clean_value(config_globals.get("MY_WEBSITE"))

CF_CLEARANCE = clean_value(config_globals.get("CF_CLEARANCE"))

# cookie cf_clearance kamu (ganti sesuai aktif)

EXTRA_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
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
    # user-agent di-set juga di new_context(), tapi tambahkan di header untuk berjaga
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}

headers = {"User-Agent": USER_AGENT}
translator = GoogleTranslator(source="vi", target="en")

# =====================================================
# PARSE BANTU
# =====================================================
def parse_time_from_slug(slug: str):
    m = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if m:
        h, mi, d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{mi}"
    return "??/??-??.??"

def parse_title_from_slug(slug: str):
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    try:
        translated = translator.translate(title_part)
        return f"{title_part} ({translated})"
    except Exception:
        return title_part

# =====================================================
# PLAYWRIGHT FETCH STREAM
# =====================================================
async def fetch_stream_url(page_url, headless=True):
    found = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=USER_AGENT)
        await context.set_extra_http_headers(EXTRA_HEADERS)

        page = await context.new_page()
        await page.goto(page_url, timeout=60000)

        iframe = await page.query_selector("iframe#iframe-stream") or await page.query_selector("iframe")
        if not iframe:
            await browser.close()
            return None

        iframe_src = await iframe.get_attribute("src")
        if not iframe_src:
            await browser.close()
            return None

        # Tambahkan cookie cf_clearance untuk domain iframe
        parsed = urlparse(iframe_src)
        if parsed.hostname:
            await context.add_cookies([{
                "name": "cf_clearance",
                "value": CF_CLEARANCE,
                "domain": parsed.hostname,
                "path": "/",
                "secure": True
            }])

        iframe_page = await context.new_page()
        await iframe_page.set_extra_http_headers({**EXTRA_HEADERS, "referer": page_url})

        found_url = None

        async def on_response(resp):
            nonlocal found_url
            try:
                u = resp.url
                if ".m3u8" in u:
                    found_url = u
            except Exception:
                pass

        iframe_page.on("response", on_response)

        try:
            await iframe_page.goto(iframe_src, timeout=60000)
            await asyncio.sleep(5)
        except Exception:
            pass

        # cek HTML juga
        html = await iframe_page.content()
        m = re.search(r'https?://[^"\']+\.m3u8', html)
        if m:
            found_url = m.group(0)

        await browser.close()
        return found_url

# =====================================================
# PROSES HALAMAN UTAMA
# =====================================================
print("🌐 Mengambil halaman utama...")
resp = requests.get(BASE_URL, headers=headers)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

output_lines = ["#EXTM3U"]
seen = set()

async def process_all():
    for tab_id in TABS:
        tab = soup.select_one(f"#{tab_id}")
        if not tab:
            print(f"⚠️ Tab '{tab_id}' tidak ditemukan.")
            continue

        print(f"✅ Memproses tab: {tab_id}")
        links = [a.get("href") for a in tab.select("a[href*='/truc-tiep/']") if a.get("href")]
        for href in links:
            slug = href.strip("/")

            if slug in seen:
                continue
            seen.add(slug)

            match_time = parse_time_from_slug(slug)
            title = parse_title_from_slug(slug)
            page_url = f"{BASE_URL.rstrip('/')}/{slug}/"

            print(f"🎯 {title} → ambil stream...")
            m3u8_url = await fetch_stream_url(page_url, headless=True)

            if not m3u8_url:
                # fallback ke website proxy
                if "?slug=" in MY_WEBSITE:
                    stream_link = f"{MY_WEBSITE}{slug}"
                else:
                    stream_link = f"{MY_WEBSITE}?slug={slug}"
            else:
                stream_link = m3u8_url

            output_lines.append(
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title}'
            )
            output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
            output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
            output_lines.append(stream_link)

# =====================================================
# JALANKAN
# =====================================================
asyncio.run(process_all())

filename = "Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"\n✅ File M3U tersimpan: {filename}")
