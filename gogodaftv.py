import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
from pathlib import Path
from charset_normalizer import from_bytes
from curl_cffi import requests

# ==========================
# Timezone
# ==========================
try:
    from zoneinfo import ZoneInfo
    SHANGHAI = ZoneInfo("Asia/Shanghai")  # UTC+8
    JAKARTA = ZoneInfo("Asia/Jakarta")    # UTC+7
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
    "Origin": BASE_URL.rstrip("/"),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ==========================
# Translate
# ==========================
translation_cache = {}


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
        await asyncio.sleep(0.2)

        return translated

    except Exception as e:
        print(f"Translate error for '{text}': {e}")
        return text


# ==========================
# Fetch HTML
# ==========================
async def fetch_html(session, url):
    try:
        timeout = aiohttp.ClientTimeout(total=20)

        async with session.get(
            url,
            headers=HEADERS,
            ssl=False,
            timeout=timeout,
            allow_redirects=True
        ) as response:

            print(f"HTTP Status: {response.status}")
            print(f"Final URL: {response.url}")
            print(f"Content-Type: {response.headers.get('Content-Type')}")

            if response.status != 200:
                print("⚠️ Non-200 response")
                return ""

            raw = await response.read()

            print(f"Downloaded bytes: {len(raw)}")

            # Auto detect encoding
            try:
                detected = from_bytes(raw).best()

                if detected:
                    html = str(detected)
                    print(f"Detected encoding: {detected.encoding}")

                    if "<html" in html.lower():
                        return html

            except Exception as e:
                print(f"Charset detect error: {e}")

            # Manual fallback
            encodings = [
                "utf-8",
                "gbk",
                "gb2312",
                "big5",
                "latin-1"
            ]

            for enc in encodings:
                try:
                    html = raw.decode(enc, errors="ignore")

                    if "<html" in html.lower():
                        print(f"Fallback encoding success: {enc}")
                        return html

                except Exception:
                    continue

            # Last fallback
            return raw.decode("utf-8", errors="replace")

    except Exception as e:
        print(f"Fetch error: {e}")
        return ""


# ==========================
# Parse Matches
# ==========================
async def parse_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    lines = []

    a_tags = soup.select("a.clearfix")

    if not a_tags:
        print("⚠️ No matches found.")
        return lines

    print(f"Found matches: {len(a_tags)}")

    for a_tag in a_tags:

        try:
            match_url = a_tag.get("href", "").strip()

            if not match_url:
                continue

            match_id = match_url.rstrip("/").split("/")[-1]

            section = a_tag.find("section", class_="jiabifeng")

            if not section:
                continue

            # ==========================
            # Teams
            # ==========================
            home_div = section.find("div", class_="team zhudui")
            away_div = section.find("div", class_="team kedui")

            home_team = (
                home_div.p.get_text(strip=True)
                if home_div and home_div.p else ""
            )

            away_team = (
                away_div.p.get_text(strip=True)
                if away_div and away_div.p else ""
            )

            if not home_team and not away_team:
                continue

            # Translate
            home_team_en = await translate_zh_to_en(home_team)
            away_team_en = await translate_zh_to_en(away_team)

            # ==========================
            # League & Time
            # ==========================
            liga_name = ""
            event_time = ""

            center_div = section.find("div", class_="center")

            if center_div:
                liga_tag = center_div.find("p", class_="eventtime_wuy")

                if liga_tag:

                    em = liga_tag.find("em")
                    i_tag = liga_tag.find("i")

                    liga_name = (
                        em.get_text(strip=True)
                        if em else ""
                    )

                    event_time = (
                        i_tag.get_text(strip=True)
                        if i_tag else ""
                    )

            # Translate league
            liga_name_en = await translate_zh_to_en(liga_name)

            # ==========================
            # Convert Time
            # ==========================
            data_time = a_tag.get("data-time", "").strip()

            try:
                dt_obj = datetime.strptime(
                    f"{data_time} {event_time}",
                    "%Y-%m-%d %H:%M"
                )

                dt_obj = dt_obj.replace(tzinfo=SHANGHAI)
                dt_obj = dt_obj.astimezone(JAKARTA)

                dt_str = dt_obj.strftime("%d/%m-%H.%M")

            except Exception as e:
                print(
                    f"⚠️ Time parse error "
                    f"for {data_time} {event_time}: {e}"
                )

                dt_str = f"{data_time}-{event_time}"

            # ==========================
            # Build Title
            # ==========================
            title = (
                f"{home_team_en} vs "
                f"{away_team_en} "
                f"({liga_name_en})"
            )

            # ==========================
            # M3U
            # ==========================
            lines.append(
                f'#EXTINF:-1 '
                f'group-title="⚽️| LIVE EVENT" '
                f'tvg-logo="{LOGO_URL}",'
                f'{dt_str} {title}'
            )

            lines.append(
                f'#EXTVLCOPT:http-user-agent='
                f'{HEADERS["User-Agent"]}'
            )

            lines.append(
                f'#EXTVLCOPT:http-referrer='
                f'{BASE_URL}'
            )

            lines.append(f"{WORKER_URL}{match_id}")

            print(f"✅ Parsed: {title}")

        except Exception as e:
            print(f"Parse match error: {e}")
            continue

    return lines


# ==========================
# Main
# ==========================
async def main():

    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(
        connector=connector
    ) as session:

        html = await fetch_html(session, TARGET_URL)

        if not html:
            print("⚠️ Failed to fetch HTML. Exiting.")
            return

        print(f"HTML length: {len(html)}")

        lines = await parse_matches(html)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

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
