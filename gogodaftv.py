import asyncio
import json
import re

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path

from curl_cffi import requests

import argostranslate.package
import argostranslate.translate


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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


HEADERS = {

    "User-Agent": USER_AGENT,

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
# ARGOS CONFIG
# =========================================================

ARGOS_FROM = "zh"
ARGOS_TO = "en"

# Jumlah translasi paralel.
#
# Argos lokal tidak kena HTTP 429.
# Tetapi terlalu banyak thread bisa membebani CPU/RAM.
#
# 4 biasanya aman untuk GitHub Actions.
ARGOS_CONCURRENCY = 4


ARGOS_INDEX_URL = (
    "https://raw.githubusercontent.com/"
    "argosopentech/argospm-index/main/index.json"
)


# =========================================================
# CACHE
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
# ARGOS LANGUAGE
# =========================================================

def get_installed_languages():

    try:

        return (
            argostranslate.translate
            .get_installed_languages()
        )

    except Exception as e:

        print(
            f"⚠️ Failed to get Argos languages: "
            f"{e}"
        )

        return []


def get_argos_translator():

    languages = get_installed_languages()

    from_lang = None
    to_lang = None

    for lang in languages:

        code = getattr(
            lang,
            "code",
            ""
        )

        if code == ARGOS_FROM:
            from_lang = lang

        elif code == ARGOS_TO:
            to_lang = lang


    if not from_lang:

        raise RuntimeError(
            "Argos Chinese language "
            "model not installed"
        )


    if not to_lang:

        raise RuntimeError(
            "Argos English language "
            "model not installed"
        )


    try:

        translator = (
            from_lang
            .get_translation(to_lang)
        )

    except Exception as e:

        raise RuntimeError(
            f"Unable to get Argos translator: {e}"
        )


    if not translator:

        raise RuntimeError(
            "Argos zh → en translator not found"
        )


    return translator


# =========================================================
# INSTALL ARGOS MODEL
# =========================================================

def install_argos_model():

    print(
        "🌐 Checking Argos "
        "Chinese → English model..."
    )


    # -----------------------------------------------------
    # CHECK EXISTING
    # -----------------------------------------------------

    try:

        translator = get_argos_translator()

        if translator:

            print(
                "✅ Argos zh → en "
                "already installed"
            )

            return translator

    except Exception:

        pass


    # -----------------------------------------------------
    # DOWNLOAD PACKAGE LIST
    # -----------------------------------------------------

    print(
        "📋 Loading Argos package list..."
    )


    try:

        packages = (
            argostranslate.package
            .get_available_packages()
        )

    except Exception as e:

        print(
            f"❌ Failed to load Argos packages: "
            f"{e}"
        )

        return None


    if not packages:

        print(
            "❌ Argos package list empty"
        )

        return None


    print(
        f"📦 Available packages: "
        f"{len(packages)}"
    )


    # -----------------------------------------------------
    # FIND ZH -> EN
    # -----------------------------------------------------

    selected = None

    for package in packages:

        from_code = getattr(
            package,
            "from_code",
            ""
        )

        to_code = getattr(
            package,
            "to_code",
            ""
        )

        if (
            from_code == "zh"
            and
            to_code == "en"
        ):

            selected = package
            break


    if selected is None:

        print(
            "❌ Argos zh → en package "
            "not found"
        )

        return None


    version = getattr(
        selected,
        "package_version",
        "unknown"
    )


    print(
        f"📦 Found Argos zh → en "
        f"version {version}"
    )


    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    try:

        print(
            "📦 Downloading Argos "
            "zh → en model..."
        )


        package_path = (
            selected.download()
        )


        print(
            f"📦 Package downloaded: "
            f"{package_path}"
        )


        # -------------------------------------------------
        # INSTALL
        # -------------------------------------------------

        print(
            "📦 Installing Argos model..."
        )


        argostranslate.package.install_from_path(
            package_path
        )


        print(
            "✅ Argos model installed"
        )


    except Exception as e:

        print(
            f"❌ Argos installation failed: "
            f"{type(e).__name__}: {e}"
        )

        return None


    # -----------------------------------------------------
    # VERIFY
    # -----------------------------------------------------

    try:

        translator = get_argos_translator()

        if translator:

            print(
                "✅ Verified: "
                "Argos zh → en is ready"
            )

            return translator

    except Exception as e:

        print(
            f"❌ Argos verification failed: "
            f"{e}"
        )


    return None


# =========================================================
# ARGOS TRANSLATE ONE
# =========================================================

def translate_sync(
    translator,
    text
):

    text = text.strip()

    if not text:
        return ""


    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    if text in translation_cache:

        return translation_cache[text]


    # -----------------------------------------------------
    # NO CHINESE
    # -----------------------------------------------------

    if not contains_chinese(text):

        translation_cache[text] = text

        return text


    # -----------------------------------------------------
    # ARGOS
    # -----------------------------------------------------

    try:

        translated = (
            translator
            .translate(text)
        )


        if translated:

            translated = (
                str(translated)
                .replace("\n", " ")
                .strip()
            )


            if translated:

                translation_cache[
                    text
                ] = translated


                return translated


    except Exception as e:

        print(
            f"⚠️ Argos failed: "
            f"{text} -> {e}"
        )


    # -----------------------------------------------------
    # FALLBACK
    # -----------------------------------------------------

    translation_cache[
        text
    ] = text

    return text


# =========================================================
# ASYNC TRANSLATE ONE
# =========================================================

async def translate_one(
    translator,
    text,
    semaphore
):

    async with semaphore:

        result = await asyncio.to_thread(
            translate_sync,
            translator,
            text
        )

        return (
            text,
            result
        )


# =========================================================
# TRANSLATE ALL
# =========================================================

async def translate_all(
    texts,
    translator
):

    # -----------------------------------------------------
    # UNIQUE
    # -----------------------------------------------------

    unique_texts = list(
        dict.fromkeys(
            x.strip()
            for x in texts
            if x and x.strip()
        )
    )


    # -----------------------------------------------------
    # NEED TRANSLATION
    # -----------------------------------------------------

    need_translation = [

        x

        for x in unique_texts

        if (
            x not in translation_cache
            and
            contains_chinese(x)
        )

    ]


    print()
    print(
        f"📦 Total unique names: "
        f"{len(unique_texts)}"
    )

    print(
        f"📦 Need translation: "
        f"{len(need_translation)}"
    )


    # -----------------------------------------------------
    # NOTHING TO DO
    # -----------------------------------------------------

    if not need_translation:

        print(
            "✅ Semua nama sudah ada "
            "di cache"
        )

        return {
            x: translation_cache.get(
                x,
                x
            )
            for x in unique_texts
        }


    print()
    print(
        f"🚀 Translating "
        f"{len(need_translation)} "
        f"names with local Argos..."
    )

    print(
        f"⚙️ Parallel workers: "
        f"{ARGOS_CONCURRENCY}"
    )


    semaphore = asyncio.Semaphore(
        ARGOS_CONCURRENCY
    )


    # -----------------------------------------------------
    # CREATE TASKS
    # -----------------------------------------------------

    tasks = [

        translate_one(
            translator,
            text,
            semaphore
        )

        for text in need_translation

    ]


    # -----------------------------------------------------
    # ASYNCIO GATHER
    # -----------------------------------------------------

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )


    # -----------------------------------------------------
    # SAVE RESULTS
    # -----------------------------------------------------

    completed = 0

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


        completed += 1


        print(
            f"[{completed}/"
            f"{len(need_translation)}] "
            f"{text} → {translated}"
        )


        # Save periodically
        if completed % 25 == 0:

            save_cache()

            print(
                f"💾 Cache saved: "
                f"{completed}"
            )


    # -----------------------------------------------------
    # FINAL CACHE
    # -----------------------------------------------------

    save_cache()


    print()
    print(
        f"✅ Translation finished: "
        f"{completed}/"
        f"{len(need_translation)}"
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
# SAFE URL
# =========================================================

def safe_url(url):

    try:

        from urllib.parse import urlparse

        p = urlparse(url)

        return (
            f"{p.scheme}://"
            f"{p.netloc}/***"
        )

    except Exception:

        return "***"


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
        )

    ]


    for test_url in test_urls:

        try:

            print()
            print(
                f"🌐 Fetching: "
                f"{safe_url(test_url)}"
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
                f"{safe_url(str(response.url))}"
            )


            raw = response.content


            text = decode_html(
                raw
            )


            print(
                f"📄 HTML length: "
                f"{len(text):,}"
            )


            if (
                response.status_code == 200
                and
                len(text) > 5000
            ):

                print(
                    "✅ HTML fetch success"
                )

                return text


            print(
                "⚠️ Invalid response"
            )


        except Exception as e:

            print(
                f"❌ Fetch error: "
                f"{type(e).__name__}: "
                f"{e}"
            )


    return ""


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# PARSE MATCHES
# =========================================================

async def parse_matches(
    html,
    translator
):

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


    print()
    print(
        f"📺 Found possible matches: "
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
    # =====================================================

    for a_tag in a_tags:

        try:

            match_url = (
                a_tag
                .get(
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

                    home_team = clean_text(
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

                    away_team = clean_text(
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
            # LEAGUE
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

                        liga_name = clean_text(
                            em.get_text(
                                strip=True
                            )
                        )


                    if i_tag:

                        event_time = clean_text(
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
                f"⚠️ Parse match error: "
                f"{e}"
            )


    # =====================================================
    # COLLECT ALL NAMES
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
    # TRANSLATE ALL
    # =====================================================

    translations = await translate_all(
        all_names,
        translator
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

            f"{home_team_en} "
            f"vs "
            f"{away_team_en}"

        )


        if liga_name_en:

            title += (
                f" ({liga_name_en})"
            )


        title = clean_text(
            title
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
            f'{USER_AGENT}'

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


    return lines


# =========================================================
# MAIN
# =========================================================

async def main():

    print(
        "========================================"
    )

    print(
        "🚀 GOGODATV"
    )

    print(
        "🌐 LOCAL ARGOS TRANSLATION"
    )

    print(
        "========================================"
    )


    # =====================================================
    # INSTALL / LOAD ARGOS
    # =====================================================

    translator = install_argos_model()


    if not translator:

        print(
            "❌ Argos translator unavailable"
        )

        return


    print(
        "✅ Local zh → en translator ready"
    )


    # =====================================================
    # FETCH
    # =====================================================

    html = ""


    for i in range(3):

        print()
        print(
            f"🔄 Fetch retry "
            f"{i + 1}/3"
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
            "❌ Failed to fetch HTML. "
            "Exiting."
        )

        return


    print()
    print(
        f"📄 HTML length: "
        f"{len(html):,}"
    )


    # =====================================================
    # PARSE
    # =====================================================

    lines = await parse_matches(
        html,
        translator
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

    print()
    print(
        "========================================"
    )


    if lines:

        print(
            f"✅ Total matches: "
            f"{len(lines) // 4}"
        )

        print(
            f"💾 M3U: "
            f"{OUTPUT_FILE.resolve()}"
        )

        print(
            f"💾 Cache: "
            f"{CACHE_FILE.resolve()}"
        )

    else:

        print(
            "⚠️ No valid matches found."
        )

        print(
            f"💾 Empty M3U: "
            f"{OUTPUT_FILE.resolve()}"
        )


    print(
        "========================================"
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
