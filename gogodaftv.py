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
PROXY_URL = config_vars.get("PROXY_URL", "").strip()

TARGET_URL = BASE_URL

OUTPUT_FILE = Path(__file__).parent / "gogodatv.m3u"

CACHE_FILE = Path(__file__).parent / "proxy_cache.txt"

FAILED_FILE = Path(__file__).parent / "proxy_failed.txt"

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


# ===============================
# PROXY
# ===============================
def get_proxy_list(url):

    try:
        res = requests.get(
            url,
            impersonate="chrome136",
            timeout=15,
            verify=False
        )

        res.raise_for_status()

        proxies = [
            p.strip()
            for p in res.text.splitlines()
            if p.strip()
        ]

        print(f"[✓] Total proxy loaded: {len(proxies)}")

        return proxies

    except Exception as e:
        print(
            f"[!] Gagal ambil proxy list: {e}",
            file=sys.stderr
        )

        return []


def simpan_cache_berhasil(proxy):

    try:
        CACHE_FILE.write_text(proxy)

        print(
            f"[✓] Proxy disimpan ke cache: {proxy}",
            file=sys.stderr
        )

    except Exception:
        pass


def simpan_cache_gagal(proxy):

    try:
        with FAILED_FILE.open("a") as f:
            f.write(proxy + "\n")

    except Exception:
        pass

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

    proxy_list = get_proxy_list(PROXY_URL)

    # coba cache dulu
    if CACHE_FILE.exists():

        cached_proxy = CACHE_FILE.read_text().strip()

        if cached_proxy:
            proxy_list.insert(0, cached_proxy)

    tested = set()

    for proxy in proxy_list:

        proxy = proxy.strip()

        if not proxy or proxy in tested:
            continue

        tested.add(proxy)

        try:
            print(f"\n[•] Mencoba proxy: {proxy}")

            proxies = {
                "http": proxy,
                "https": proxy
            }

            response = requests.get(
                url,

                headers=HEADERS,

                proxies=proxies,

                impersonate="chrome136",

                timeout=20,

                verify=False,

                allow_redirects=True,

                http_version=1
            )

            print(f"HTTP Status: {response.status_code}")
            print(f"Final URL: {response.url}")

            raw = response.content

            # bypass fake 502
            text_preview = response.text[:3000]

            if (
                "a.clearfix" in text_preview
                or "jiabifeng" in text_preview
                or "eventtime_wuy" in text_preview
            ):
                print("✅ HTML valid ditemukan")

                simpan_cache_berhasil(proxy)

                return response.text

            if response.status_code != 200:

                print("⚠️ Non-200 response")

                simpan_cache_gagal(proxy)

                continue

            # auto detect encoding
            try:
                detected = from_bytes(raw).best()

                if detected:

                    html = str(detected)

                    if "<html" in html.lower():

                        print(
                            f"✅ Success with encoding: "
                            f"{detected.encoding}"
                        )

                        simpan_cache_berhasil(proxy)

                        return html

            except Exception:
                pass

            # manual fallback
            for enc in [
                "utf-8",
                "gbk",
                "gb2312",
                "big5",
                "latin-1"
            ]:

                try:
                    html = raw.decode(
                        enc,
                        errors="ignore"
                    )

                    if "<html" in html.lower():

                        print(f"✅ Success with {enc}")

                        simpan_cache_berhasil(proxy)

                        return html

                except Exception:
                    continue

            simpan_cache_gagal(proxy)

        except Exception as e:

            print(
                f"[×] Proxy gagal: {proxy} → {e}",
                file=sys.stderr
            )

            simpan_cache_gagal(proxy)

            continue

    print("⚠️ Semua proxy gagal")

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

            # ==========================
            # Translate Teams
            # ==========================
            home_team_en = await translate_zh_to_en(home_team)

            away_team_en = await translate_zh_to_en(away_team)

            # ==========================
            # League & Time
            # ==========================
            liga_name = ""

            event_time = ""

            center_div = section.find("div", class_="center")

            if center_div:

                liga_tag = center_div.find(
                    "p",
                    class_="eventtime_wuy"
                )

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

            liga_name_en = await translate_zh_to_en(liga_name)

            # ==========================
            # Time Convert
            # ==========================
            data_time = a_tag.get("data-time", "").strip()

            try:
                dt_obj = datetime.strptime(
                    f"{data_time} {event_time}",
                    "%Y-%m-%d %H:%M"
                )

                dt_obj = dt_obj.replace(
                    tzinfo=SHANGHAI
                )

                dt_obj = dt_obj.astimezone(
                    JAKARTA
                )

                dt_str = dt_obj.strftime(
                    "%d/%m-%H.%M"
                )

            except Exception as e:

                print(
                    f"⚠️ Time parse error "
                    f"{data_time} {event_time}: {e}"
                )

                dt_str = f"{data_time}-{event_time}"

            # ==========================
            # Title
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
