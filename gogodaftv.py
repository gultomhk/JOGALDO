import asyncio
import sys

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
from pathlib import Path
from charset_normalizer import from_bytes

from curl_cffi import requests, CurlError


# ==========================
# Timezone
# ==========================
try:
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo("Asia/Shanghai")
    JAKARTA = ZoneInfo("Asia/Jakarta")

except Exception:
    SHANGHAI = timezone(timedelta(hours=8))
    JAKARTA = timezone(timedelta(hours=7))


# ==========================
# Load Config
# ==========================
GOGODATTVDATA_FILE = Path.home() / "gogodattvdata_file.txt"

config_vars = {}

with open(GOGODATTVDATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL", "").strip()
WORKER_URL = config_vars.get("WORKER_URL", "").strip()
LOGO_URL = config_vars.get("LOGO_URL", "").strip()

TARGET_URL = BASE_URL

OUTPUT_FILE = Path(__file__).parent / "gogodatv.m3u"


# ==========================
# Headers
# ==========================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/webp,*/*;q=0.8"
    ),

    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",

    "Accept-Encoding": "gzip, deflate, br",

    "Cache-Control": "no-cache",

    "Pragma": "no-cache",

    "Connection": "keep-alive",

    "Referer": BASE_URL,

    "Origin": BASE_URL.rstrip("/")
}


# ==========================
# Translation Cache
# ==========================
translation_cache = {}


# ==========================
# Translate
# ==========================
async def translate_zh_to_en(text):

    if not text:
        return ""

    if text in translation_cache:
        return translation_cache[text]

    try:
        translated = GoogleTranslator(
            source="zh-CN",
            target="en"
        ).translate(text)

        translation_cache[text] = translated

        await asyncio.sleep(0.15)

        return translated

    except Exception as e:

        print(f"Translate error for '{text}': {e}")

        return text


# ==========================
# Fetch HTML
# ==========================
async def fetch_html(url):

    test_urls = [
        url,
        url.replace("https://", "http://"),
        url.replace("www.", ""),
    ]

    for test_url in test_urls:

        try:
            print(f"\nTrying: {test_url}")

            response = requests.get(
                test_url,
                headers=HEADERS,
                impersonate="chrome136",
                timeout=30,
                verify=False,
                allow_redirects=True,
                http_version=1
            )

            print(f"HTTP Status: {response.status_code}")
            print(f"Final URL: {response.url}")

            # FIX ENCODING
            raw = response.content

            detected = from_bytes(raw).best()

            if detected:
                text = str(detected)
            else:
                text = raw.decode("utf-8", errors="ignore")

            print(text[:500])

            if response.status_code == 200 and len(text) > 5000:
                print("✅ Success")
                return text

            print("⚠️ Invalid response")

        except Exception as e:
            print(f"Fetch error: {e}")

    return ""


# ==========================
# Parse Matches
# ==========================
async def parse_matches(html):

    soup = BeautifulSoup(html, "html.parser")

    lines = []

    # FLEXIBLE SELECTOR
    a_tags = soup.select(
        "a.clearfix, a[href*='match'], a[href*='live'], div.list a"
    )

    # filter duplicate
    seen = set()
    filtered = []

    for a in a_tags:

        href = a.get("href", "").strip()

        if not href:
            continue

        if href in seen:
            continue

        seen.add(href)
        filtered.append(a)

    a_tags = filtered

    print(f"Found possible matches: {len(a_tags)}")

    if not a_tags:
        print("⚠️ No matches found.")

        # DEBUG SAVE
        debug_file = Path(__file__).parent / "debug.html"

        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"⚠️ HTML dumped: {debug_file}")

        return lines

    for a_tag in a_tags:

        try:

            match_url = a_tag.get("href", "").strip()

            if not match_url:
                continue

            match_id = (
                match_url.rstrip("/")
                .split("/")[-1]
            )

            text = a_tag.get_text(" ", strip=True)

            if len(text) < 5:
                continue

            # coba ambil team
            parts = text.split()

            title = " ".join(parts[:10])

            lines.append(
                f'#EXTINF:-1 '
                f'group-title="⚽️| LIVE EVENT" '
                f'tvg-logo="{LOGO_URL}",'
                f'{title}'
            )

            lines.append(
                f'#EXTVLCOPT:http-user-agent='
                f'{HEADERS["User-Agent"]}'
            )

            lines.append(
                f'#EXTVLCOPT:http-referrer='
                f'{BASE_URL}'
            )

            lines.append(
                f"{WORKER_URL}{match_id}"
            )

            print(f"✅ Parsed: {title}")

        except Exception as e:

            print(f"Parse match error: {e}")

            continue

    return lines


# ==========================
# Main
# ==========================
async def main():

    html = ""

    # retry fetch
    for i in range(3):

        print(f"\nRetry {i+1}/3")

        html = await fetch_html(TARGET_URL)

        if html:
            break

        await asyncio.sleep(5)

    if not html:
        print("⚠️ Failed to fetch HTML. Exiting.")
        return

    print(f"HTML length: {len(html)}")

    lines = await parse_matches(html)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")

        if lines:
            f.write("\n".join(lines))

    if lines:
        print(f"✅ Total matches parsed: {len(lines)//4}")
        print(f"✅ M3U saved: {OUTPUT_FILE.resolve()}")

    else:
        print("⚠️ No valid matches found.")
        print(f"⚠️ Empty M3U created: {OUTPUT_FILE.resolve()}")

# ==========================
# Start
# ==========================
if __name__ == "__main__":
    asyncio.run(main())
