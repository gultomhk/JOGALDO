import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, quote

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
CHINZAKODOK_FILE = Path.home() / "chinzakodok_file.txt"

config_vars = {}

with open(CHINZAKODOK_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL")
WORKER_URL = config_vars.get("WORKER_URL")
LOGO_URL = config_vars.get("LOGO_URL")

TARGET_URL = BASE_URL

OUTPUT_FILE = Path(__file__).parent / "CHINZAKODOK.m3u"


# ==========================
# Headers
# ==========================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# =========================================================
# TRANSLATION CACHE
# =========================================================
TRANSLATION_CACHE = {}


# =========================================================
# Translate Chinese -> English
# =========================================================
async def translate_zh_to_en(session, text):

    if not text:
        return ""

    text = text.strip()

    # ==========================
    # Cache
    # ==========================
    if text in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[text]

    # ==========================
    # Tidak mengandung karakter China
    # ==========================
    if not any("\u4e00" <= c <= "\u9fff" for c in text):
        TRANSLATION_CACHE[text] = text
        return text

    try:

        encoded = quote(text)

        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx"
            "&sl=zh-CN"
            "&tl=en"
            "&dt=t"
            f"&q={encoded}"
        )

        async with session.get(
            url,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:

            if response.status != 200:

                print(
                    f"⚠️ Translate HTTP {response.status}: {text}"
                )

                TRANSLATION_CACHE[text] = text

                return text

            data = await response.json(content_type=None)

            result = ""

            # ==========================
            # Parse Google response
            # ==========================
            if data and isinstance(data[0], list):

                for item in data[0]:

                    if item and len(item) > 0:
                        result += item[0]

            result = result.strip()

            if result:

                TRANSLATION_CACHE[text] = result

                print(
                    f"🌐 {text} -> {result}"
                )

                return result

    except Exception as e:

        print(
            f"⚠️ Translate failed '{text}': "
            f"{type(e).__name__}: {e}"
        )

    # ==========================
    # Fallback nama asli
    # ==========================
    TRANSLATION_CACHE[text] = text

    print(
        f"⚠️ Translation unavailable: {text}"
    )

    return text


# =========================================================
# Translate semua nama tim secara PARALLEL
# =========================================================
async def translate_all_teams(session, team_names):

    # ==========================
    # Hilangkan duplikat
    # ==========================
    unique_names = list(dict.fromkeys(
        name.strip()
        for name in team_names
        if name and name.strip()
    ))

    if not unique_names:
        return {}

    print(
        f"🌐 Translating {len(unique_names)} unique team names..."
    )

    # ==========================
    # asyncio.gather
    # ==========================
    results = await asyncio.gather(
        *[
            translate_zh_to_en(session, name)
            for name in unique_names
        ],
        return_exceptions=True
    )

    translated = {}

    for original, result in zip(unique_names, results):

        if isinstance(result, Exception):

            print(
                f"⚠️ Translation exception "
                f"'{original}': {result}"
            )

            translated[original] = original

        else:

            translated[original] = result

    print(
        f"✅ Translation completed: "
        f"{len(translated)} teams"
    )

    return translated


# =========================================================
# Safe URL
# =========================================================
def safe_url(url):

    try:

        p = urlparse(url)

        return f"{p.scheme}://{p.netloc}/***"

    except Exception:

        return "***"


# =========================================================
# Fetch HTML
# =========================================================
async def fetch_html(session, url):

    try:

        async with session.get(
            url,
            headers=HEADERS,
            ssl=False,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as response:

            print(
                f"GET : {safe_url(str(response.url))}"
            )

            print(
                f"HTTP: {response.status}"
            )

            if response.history:

                print("Redirects:")

                for r in response.history:

                    print(
                        f"  {r.status} -> {r.url}"
                    )

            text = await response.text(
                errors="ignore"
            )

            if response.status != 200:

                print(
                    "Response (first 500 chars):\n"
                    f"{text[:500]}"
                )

                return ""

            return text

    except asyncio.TimeoutError:

        print(
            f"Fetch timeout: {url}"
        )

        return ""

    except aiohttp.ClientConnectorError as e:

        print(
            f"Connection error: "
            f"{e.host}:{e.port}"
        )

        print(repr(e))

        return ""

    except aiohttp.ClientResponseError as e:

        print(
            f"HTTP error: {e.status}"
        )

        print(repr(e))

        return ""

    except aiohttp.ClientError as e:

        print(
            f"aiohttp error: "
            f"{type(e).__name__}"
        )

        print(repr(e))

        return ""

    except Exception as e:

        print(
            f"Unexpected error: "
            f"{type(e).__name__}"
        )

        print(repr(e))

        return ""


# =========================================================
# Parse Matches
# =========================================================
async def parse_matches(html, session):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    lines = []

    a_tags = soup.select(
        "a.clearfix"
    )

    if not a_tags:

        print(
            "⚠️ No matches found in the HTML."
        )

        return lines

    # =====================================================
    # STEP 1
    # Ambil semua data pertandingan
    # =====================================================
    matches = []

    all_team_names = []

    for a_tag in a_tags:

        match_url = a_tag.get(
            "href",
            ""
        )

        if not match_url:
            continue

        match_id = (
            match_url
            .rstrip("/")
            .split("/")[-1]
        )

        section = a_tag.find(
            "section",
            class_="jiabifeng"
        )

        if not section:
            continue

        # =================================================
        # Home
        # =================================================
        home_div = section.find(
            "div",
            class_="team zhudui"
        )

        home_team = (
            home_div.p.text.strip()
            if home_div and home_div.p
            else ""
        )

        # =================================================
        # Away
        # =================================================
        away_div = section.find(
            "div",
            class_="team kedui"
        )

        away_team = (
            away_div.p.text.strip()
            if away_div and away_div.p
            else ""
        )

        # Simpan nama tim
        if home_team:
            all_team_names.append(
                home_team
            )

        if away_team:
            all_team_names.append(
                away_team
            )

        # =================================================
        # Score
        # =================================================
        score_div = section.find(
            "div",
            class_="bifeng"
        )

        scores = (
            score_div
            .get_text(
                separator=":"
            )
            .strip()
            if score_div
            else "vs"
        )

        # =================================================
        # Liga + waktu
        # =================================================
        center_div = section.find(
            "div",
            class_="center"
        )

        liga_name = ""
        event_time = ""

        if center_div:

            liga_tag = center_div.find(
                "p",
                class_="eventtime_wuy"
            )

            if liga_tag:

                em = liga_tag.find("em")
                i = liga_tag.find("i")

                if em:
                    liga_name = em.text.strip()

                if i:
                    event_time = i.text.strip()

        # =================================================
        # Time
        # =================================================
        data_time = a_tag.get(
            "data-time",
            ""
        )

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
                f"for {data_time} "
                f"{event_time}: {e}"
            )

            dt_str = (
                f"{data_time}-{event_time}"
            )

        # =================================================
        # Simpan match
        # =================================================
        matches.append({
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "liga_name": liga_name,
            "dt_str": dt_str,
        })

    # =====================================================
    # STEP 2
    # Translate SEMUA tim secara paralel
    # =====================================================
    translations = await translate_all_teams(
        session,
        all_team_names
    )

    # =====================================================
    # STEP 3
    # Buat M3U
    # =====================================================
    for match in matches:

        home_team_en = translations.get(
            match["home_team"],
            match["home_team"]
        )

        away_team_en = translations.get(
            match["away_team"],
            match["away_team"]
        )

        title = (
            f"{home_team_en} vs "
            f"{away_team_en} "
            f"({match['liga_name']})"
        )

        lines.append(
            f'#EXTINF:-1 '
            f'group-title="⚽️| LIVE EVENT" '
            f'tvg-logo="{LOGO_URL}", '
            f'{match["dt_str"]} {title}'
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
            f'{WORKER_URL}{match["match_id"]}'
        )

    return lines


# =========================================================
# MAIN
# =========================================================
async def main():

    connector = aiohttp.TCPConnector(
        ssl=False,
        limit=30
    )

    timeout = aiohttp.ClientTimeout(
        total=20
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout
    ) as session:

        print(
            f"Fetching: "
            f"{safe_url(TARGET_URL)}"
        )

        html = await fetch_html(
            session,
            TARGET_URL
        )

        if not html:

            print(
                "⚠️ Failed to fetch HTML from: "
                f"{safe_url(TARGET_URL)}"
            )

            return

        lines = await parse_matches(
            html,
            session
        )

        if lines:

            with open(
                OUTPUT_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(
                    "#EXTM3U\n"
                )

                f.write(
                    "\n".join(lines)
                )

            print(
                f"✅ Total matches parsed: "
                f"{len(lines) // 4}"
            )

            print(
                "File M3U created at: "
                f"{OUTPUT_FILE.resolve()}"
            )

        else:

            with open(
                OUTPUT_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(
                    "#EXTM3U\n"
                )

            print(
                "⚠️ M3U kosong, "
                "skip push ke privat"
            )

            print(
                "Minimal file created at: "
                f"{OUTPUT_FILE.resolve()}"
            )


# =========================================================
# START
# =========================================================
if __name__ == "__main__":

    asyncio.run(main())
