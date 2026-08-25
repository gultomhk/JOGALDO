import asyncio
import json
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path

from curl_cffi import requests


# =========================================================
# TIMEZONE
# =========================================================
try:
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo("Asia/Shanghai")
    JAKARTA = ZoneInfo("Asia/Jakarta")

except Exception:
    SHANGHAI = timezone(timedelta(hours=8))
    JAKARTA = timezone(timedelta(hours=7))


# =========================================================
# LOAD CONFIG
# =========================================================
GOGODATTVDATA_FILE = (
    Path.home() /
    "gogodattvdata_file.txt"
)

config_vars = {}

with open(
    GOGODATTVDATA_FILE,
    "r",
    encoding="utf-8"
) as f:

    code = f.read()
    exec(code, config_vars)


BASE_URL = config_vars.get(
    "BASE_URL",
    ""
).strip()

WORKER_URL = config_vars.get(
    "WORKER_URL",
    ""
).strip()

LOGO_URL = config_vars.get(
    "LOGO_URL",
    ""
).strip()


TARGET_URL = BASE_URL


OUTPUT_FILE = (
    Path(__file__).parent /
    "gogodatv.m3u"
)


# =========================================================
# HEADERS
# =========================================================
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

    "Accept-Language":
        "zh-CN,zh;q=0.9,en;q=0.8",

    "Accept-Encoding":
        "gzip, deflate",

    "Cache-Control":
        "no-cache",

    "Pragma":
        "no-cache",

    "Connection":
        "keep-alive",

    "Referer":
        BASE_URL,

    "Origin":
        BASE_URL.rstrip("/")
}


# =========================================================
# LIBRETRANSLATE
# =========================================================
TRANSLATE_URL = (
    "https://de.libretranslate.com/translate"
)

TRANSLATE_SOURCE = "zh-Hans"
TRANSLATE_TARGET = "en"

TRANSLATE_API_KEY = ""

# Jangan terlalu besar.
# 3 berarti maksimal 3 request bersamaan.
TRANSLATE_CONCURRENCY = 3

# Retry ketika server rate-limit / error
TRANSLATE_RETRIES = 4


# =========================================================
# TRANSLATION CACHE
# =========================================================
CACHE_FILE = (
    Path(__file__).parent /
    "translation_cache.json"
)


def load_cache():

    if not CACHE_FILE.exists():
        return {}

    try:

        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception as e:

        print(
            f"⚠️ Cache read error: {e}"
        )

    return {}


translation_cache = load_cache()


def save_cache():

    try:

        tmp_file = CACHE_FILE.with_suffix(
            ".tmp"
        )

        with open(
            tmp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                translation_cache,
                f,
                ensure_ascii=False,
                indent=2
            )

        tmp_file.replace(
            CACHE_FILE
        )

    except Exception as e:

        print(
            f"⚠️ Cache save error: {e}"
        )


# =========================================================
# CHINESE CHECK
# =========================================================
def contains_chinese(text):

    if not text:
        return False

    return any(
        "\u4e00" <= c <= "\u9fff"
        for c in text
    )


# =========================================================
# LIBRETRANSLATE REQUEST
# =========================================================
async def libre_translate(
    session,
    text,
    semaphore
):

    text = text.strip()

    if not text:
        return ""

    # -----------------------------------------------------
    # Cache
    # -----------------------------------------------------
    if text in translation_cache:

        print(
            f"💾 CACHE: "
            f"{text} -> "
            f"{translation_cache[text]}"
        )

        return translation_cache[text]


    # -----------------------------------------------------
    # Tidak ada Chinese
    # -----------------------------------------------------
    if not contains_chinese(text):

        translation_cache[text] = text

        return text


    # -----------------------------------------------------
    # Semaphore
    # -----------------------------------------------------
    async with semaphore:

        for attempt in range(
            1,
            TRANSLATE_RETRIES + 1
        ):

            try:

                payload = {
                    "q": text,
                    "source": TRANSLATE_SOURCE,
                    "target": TRANSLATE_TARGET,
                    "format": "text",
                    "alternatives": 3,
                    "api_key": TRANSLATE_API_KEY
                }


                async with session.post(
                    TRANSLATE_URL,
                    json=payload
                ) as response:

                    status = response.status

                    # =====================================
                    # SUCCESS
                    # =====================================
                    if status == 200:

                        data = await response.json(
                            content_type=None
                        )

                        translated = (
                            data.get(
                                "translatedText"
                            )
                            if isinstance(
                                data,
                                dict
                            )
                            else None
                        )


                        if translated:

                            translated = (
                                str(translated)
                                .strip()
                            )

                            translation_cache[
                                text
                            ] = translated

                            print(
                                f"🌐 "
                                f"{text} "
                                f"→ "
                                f"{translated}"
                            )

                            return translated


                        print(
                            f"⚠️ LibreTranslate "
                            f"empty result: "
                            f"{text}"
                        )

                        break


                    # =====================================
                    # RATE LIMIT
                    # =====================================
                    if status == 429:

                        wait_time = (
                            5 * attempt
                        )

                        retry_after = (
                            response.headers.get(
                                "Retry-After"
                            )
                        )

                        if retry_after:

                            try:

                                wait_time = float(
                                    retry_after
                                )

                            except Exception:
                                pass


                        print(
                            f"⚠️ LibreTranslate "
                            f"HTTP 429: {text} "
                            f"→ retry "
                            f"{attempt}/"
                            f"{TRANSLATE_RETRIES} "
                            f"after "
                            f"{wait_time:g}s"
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue


                    # =====================================
                    # SERVER ERROR
                    # =====================================
                    if status >= 500:

                        wait_time = (
                            3 * attempt
                        )

                        print(
                            f"⚠️ LibreTranslate "
                            f"HTTP {status}: "
                            f"{text} "
                            f"→ retry "
                            f"{attempt}/"
                            f"{TRANSLATE_RETRIES}"
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue


                    # =====================================
                    # OTHER ERROR
                    # =====================================
                    body = await response.text()

                    print(
                        f"⚠️ LibreTranslate "
                        f"HTTP {status}: "
                        f"{text}"
                    )

                    print(
                        f"   Response: "
                        f"{body[:300]}"
                    )

                    break


            except Exception as e:

                wait_time = (
                    2 * attempt
                )

                print(
                    f"⚠️ Translate exception "
                    f"'{text}': "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

                if attempt < TRANSLATE_RETRIES:

                    await asyncio.sleep(
                        wait_time
                    )

                    continue

                break


    # -----------------------------------------------------
    # FALLBACK
    # -----------------------------------------------------
    print(
        f"⚠️ Translation unavailable: "
        f"{text}"
    )

    translation_cache[text] = text

    return text


# =========================================================
# TRANSLATE ALL UNIQUE NAMES
# =========================================================
async def translate_all(
    texts
):

    # unique
    unique_texts = list(
        dict.fromkeys(
            x.strip()
            for x in texts
            if x and x.strip()
        )
    )


    # hanya yang perlu translate
    need_translation = [
        x
        for x in unique_texts
        if x not in translation_cache
        and contains_chinese(x)
    ]


    print(
        f"\n📦 Total unique names: "
        f"{len(unique_texts)}"
    )

    print(
        f"📦 Need translation: "
        f"{len(need_translation)}"
    )


    if not need_translation:

        print(
            "✅ Semua tersedia di cache"
        )

        return {
            x: translation_cache.get(
                x,
                x
            )
            for x in unique_texts
        }


    # =====================================================
    # SESSION
    # =====================================================
    semaphore = asyncio.Semaphore(
        TRANSLATE_CONCURRENCY
    )


    timeout = 30


    import aiohttp

    connector = aiohttp.TCPConnector(
        limit=TRANSLATE_CONCURRENCY,
        ssl=False
    )


    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(
            total=timeout
        ),
        headers={
            "Content-Type":
                "application/json",

            "Accept":
                "application/json",

            "User-Agent":
                HEADERS["User-Agent"]
        }
    ) as session:


        # =================================================
        # TASK
        # =================================================
        async def worker(text):

            result = await libre_translate(
                session,
                text,
                semaphore
            )

            return (
                text,
                result
            )


        tasks = [
            worker(text)
            for text in need_translation
        ]


        # =================================================
        # GATHER
        # =================================================
        results = await asyncio.gather(
            *tasks,
            return_exceptions=True
        )


        for item in results:

            if isinstance(
                item,
                Exception
            ):

                print(
                    f"⚠️ Worker error: "
                    f"{item}"
                )

                continue


            text, translated = item

            translation_cache[
                text
            ] = translated


    # =====================================================
    # SAVE
    # =====================================================
    save_cache()


    print(
        f"✅ Translation finished: "
        f"{len(need_translation)} names"
    )


    return {
        x: translation_cache.get(
            x,
            x
        )
        for x in unique_texts
    }


# =========================================================
# DECODE HTML
# =========================================================
def decode_html(raw):

    encodings = [
        "utf-8",
        "gb18030",
        "gbk",
        "gb2312",
        "big5"
    ]


    for enc in encodings:

        try:

            decoded = raw.decode(
                enc
            )


            if any(
                x in decoded
                for x in [
                    "直播",
                    "足球",
                    "联赛",
                    "女",
                    "队",
                    "VS"
                ]
            ):

                print(
                    f"✅ Decoded with: "
                    f"{enc}"
                )

                return decoded


        except Exception:
            pass


    try:

        return raw.decode(
            "utf-8",
            errors="ignore"
        )

    except Exception:

        return ""


# =========================================================
# FETCH HTML
# =========================================================
async def fetch_html(url):

    test_urls = [
        url,
        url.replace(
            "https://",
            "http://"
        ),
        url.replace(
            "www.",
            ""
        ),
    ]


    for test_url in test_urls:

        try:

            print(
                f"\nTrying: "
                f"{test_url}"
            )


            response = requests.get(
                test_url,

                headers=HEADERS,

                impersonate="chrome136",

                timeout=30,

                verify=False,

                allow_redirects=True,

                http_version=1
            )


            print(
                f"HTTP Status: "
                f"{response.status_code}"
            )

            print(
                f"Final URL: "
                f"{response.url}"
            )


            raw = response.content

            text = decode_html(
                raw
            )


            print(
                "\n===== HTML PREVIEW ====="
            )

            print(
                text[:500]
            )

            print(
                "========================\n"
            )


            if (
                response.status_code == 200
                and len(text) > 5000
            ):

                print(
                    "✅ Success"
                )

                return text


            print(
                "⚠️ Invalid response"
            )


        except Exception as e:

            print(
                f"Fetch error: {e}"
            )


    return ""


# =========================================================
# PARSE MATCHES
# =========================================================
async def parse_matches(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    lines = []


    a_tags = soup.find_all(
        "a",
        href=lambda x:
            x and "/detail/" in x
    )


    print(
        f"Found possible matches: "
        f"{len(a_tags)}"
    )


    if not a_tags:

        print(
            "⚠️ No matches found."
        )

        return lines


    parsed_ids = set()

    matches = []


    # =====================================================
    # FIRST PASS
    # Ambil semua data dulu
    # =====================================================
    for a_tag in a_tags:

        try:

            match_url = (
                a_tag.get(
                    "href",
                    ""
                )
                .strip()
            )


            if not match_url:
                continue


            match_id = (
                match_url
                .rstrip("/")
                .split("/")[-1]
            )


            if match_id in parsed_ids:
                continue


            parsed_ids.add(
                match_id
            )


            # =============================================
            # HOME
            # =============================================
            home_team = ""

            home_div = a_tag.find(
                "div",
                class_="team zhudui"
            )


            if home_div:

                p = home_div.find(
                    "p"
                )

                if p:

                    home_team = (
                        p.get_text(
                            strip=True
                        )
                    )


            # =============================================
            # AWAY
            # =============================================
            away_team = ""

            away_div = a_tag.find(
                "div",
                class_="team kedui"
            )


            if away_div:

                p = away_div.find(
                    "p"
                )

                if p:

                    away_team = (
                        p.get_text(
                            strip=True
                        )
                    )


            if (
                not home_team
                and
                not away_team
            ):

                continue


            # =============================================
            # LEAGUE + TIME
            # =============================================
            liga_name = ""
            event_time = ""


            center_div = a_tag.find(
                "div",
                class_="center"
            )


            if center_div:

                liga_tag = center_div.find(
                    "p",
                    class_="eventtime_wuy"
                )


                if liga_tag:

                    em = liga_tag.find(
                        "em"
                    )

                    i_tag = liga_tag.find(
                        "i"
                    )


                    if em:

                        liga_name = (
                            em.get_text(
                                strip=True
                            )
                        )


                    if i_tag:

                        event_time = (
                            i_tag.get_text(
                                strip=True
                            )
                        )


            print(
                f"RAW: "
                f"{home_team} vs "
                f"{away_team} "
                f"({liga_name})"
            )


            matches.append({
                "match_id":
                    match_id,

                "home_team":
                    home_team,

                "away_team":
                    away_team,

                "liga_name":
                    liga_name,

                "event_time":
                    event_time,

                "data_time":
                    a_tag.get(
                        "data-time",
                        ""
                    ).strip()
            })


        except Exception as e:

            print(
                f"Parse match error: "
                f"{e}"
            )


    # =====================================================
    # COLLECT ALL TEXT
    # =====================================================
    all_names = []


    for match in matches:

        all_names.append(
            match["home_team"]
        )

        all_names.append(
            match["away_team"]
        )

        all_names.append(
            match["liga_name"]
        )


    # =====================================================
    # TRANSLATE PARALLEL
    # =====================================================
    translations = await translate_all(
        all_names
    )


    # =====================================================
    # BUILD M3U
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


        liga_name_en = translations.get(
            match["liga_name"],
            match["liga_name"]
        )


        # ===============================================
        # TIME
        # ===============================================
        try:

            dt_obj = datetime.strptime(
                f'{match["data_time"]} '
                f'{match["event_time"]}',

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
                f"⚠️ Time parse error: "
                f"{e}"
            )


            dt_str = (
                f'{match["data_time"]} '
                f'{match["event_time"]}'
            )


        # ===============================================
        # TITLE
        # ===============================================
        title = (
            f"{home_team_en} vs "
            f"{away_team_en}"
        )


        if liga_name_en:

            title += (
                f" ({liga_name_en})"
            )


        # ===============================================
        # M3U
        # ===============================================
        lines.append(
            f'#EXTINF:-1 '
            f'group-title="⚽️| LIVE EVENT" '
            f'tvg-logo="{LOGO_URL}",'
            f'{dt_str} {title}'
        )


        lines.append(
            f'#EXTVLCOPT:'
            f'http-user-agent='
            f'{HEADERS["User-Agent"]}'
        )


        lines.append(
            f'#EXTVLCOPT:'
            f'http-referrer='
            f'{BASE_URL}'
        )


        lines.append(
            f"{WORKER_URL}"
            f"{match['match_id']}"
        )


        print(
            f"✅ Parsed: {title}"
        )


    return lines


# =========================================================
# MAIN
# =========================================================
async def main():

    html = ""


    # =====================================================
    # FETCH RETRY
    # =====================================================
    for i in range(3):

        print(
            f"\nRetry {i+1}/3"
        )


        html = await fetch_html(
            TARGET_URL
        )


        if html:
            break


        await asyncio.sleep(
            5
        )


    if not html:

        print(
            "⚠️ Failed to fetch HTML. "
            "Exiting."
        )

        return


    print(
        f"HTML length: "
        f"{len(html):,}"
    )


    # =====================================================
    # PARSE
    # =====================================================
    lines = await parse_matches(
        html
    )


    # =====================================================
    # WRITE M3U
    # =====================================================
    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "#EXTM3U\n"
        )


        if lines:

            f.write(
                "\n".join(lines)
            )


    # =====================================================
    # RESULT
    # =====================================================
    if lines:

        print(
            f"✅ Total matches parsed: "
            f"{len(lines) // 4}"
        )


        print(
            f"✅ M3U saved: "
            f"{OUTPUT_FILE.resolve()}"
        )


    else:

        print(
            "⚠️ No valid matches found."
        )


        print(
            f"⚠️ Empty M3U created: "
            f"{OUTPUT_FILE.resolve()}"
        )


# =========================================================
# START
# =========================================================
if __name__ == "__main__":

    asyncio.run(
        main()
    )
