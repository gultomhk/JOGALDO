import aiohttp
import asyncio
import json
import requests
import os
import tempfile
import zipfile
import re

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import argostranslate.package
import argostranslate.translate

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

DEBUG_HTML_FILE = (
    Path(__file__).parent /
    "original_debug.html"
)

TRANSLATION_CACHE_FILE = (
    Path(__file__).parent /
    "translation_cache.json"
)


# =========================================================
# ARGOS PACKAGE
# =========================================================

ARGOS_INDEX_URL = (
    "https://raw.githubusercontent.com/"
    "argosopentech/argospm-index/main/index.json"
)


# =========================================================
# LOAD CACHE
# =========================================================

def load_translation_cache():
    if not TRANSLATION_CACHE_FILE.exists():
        return {}

    try:
        with open(TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"⚠️ Cache read error: {e}")

    return {}


TRANSLATION_CACHE = load_translation_cache()


# =========================================================
# SAVE CACHE
# =========================================================

def save_translation_cache():
    try:
        with open(TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(TRANSLATION_CACHE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Cache save error: {e}")


# =========================================================
# SAFE URL
# =========================================================

def safe_url(url):
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/***"
    except Exception:
        return "***"


# =========================================================
# CHINESE CHECK
# =========================================================

def contains_chinese(text):
    if not text:
        return False
    return any("\u4e00" <= c <= "\u9fff" for c in text)


# =========================================================
# GET INSTALLED LANGUAGES
# =========================================================

def get_argos_languages():
    try:
        return argostranslate.translate.get_installed_languages()
    except Exception as e:
        print(f"⚠️ Failed to read Argos languages: {type(e).__name__}: {e}")
        return []


# =========================================================
# FIND LANGUAGE
# =========================================================

def find_language(languages, code):
    for lang in languages:
        if getattr(lang, "code", None) == code:
            return lang
    return None


# =========================================================
# CHECK ZH -> EN TRANSLATOR
# =========================================================

def get_installed_zh_en():
    languages = get_argos_languages()
    if not languages:
        return None

    zh_lang = find_language(languages, "zh")
    en_lang = find_language(languages, "en")

    if not zh_lang or not en_lang:
        return None

    try:
        translator = zh_lang.get_translation(en_lang)
        if translator:
            return translator
    except Exception:
        pass

    return None


# =========================================================
# INSTALL USING ARGOS PACKAGE API
# =========================================================

def install_using_argos_api():
    print("🔎 Checking Argos package API...")

    try:
        get_packages = getattr(argostranslate.package, "get_available_packages", None)
        if not callable(get_packages):
            print("⚠️ get_available_packages() not available")
            return False

        print("📋 Loading Argos package list...")
        packages = get_packages()

        if not packages:
            print("⚠️ Argos package list is empty")
            return False

        print(f"📦 Available packages: {len(packages)}")

        selected = None
        for package in packages:
            from_code = getattr(package, "from_code", None)
            to_code = getattr(package, "to_code", None)
            if from_code == "zh" and to_code == "en":
                selected = package
                break

        if selected is None:
            print("⚠️ zh → en package not found through Argos API")
            return False

        version = getattr(selected, "package_version", "unknown")
        print(f"📦 Found Argos zh → en version {version}")

        download_method = getattr(selected, "download", None)
        if not callable(download_method):
            print("⚠️ Argos package does not support download()")
            return False

        print("📦 Downloading Argos zh → en model...")
        package_path = download_method()

        if not package_path:
            print("❌ Argos returned empty package path")
            return False

        print(f"📦 Package downloaded: {package_path}")
        print("📦 Installing Argos model...")

        argostranslate.package.install_from_path(package_path)
        print("✅ Argos model installed")

        translator = get_installed_zh_en()
        if translator:
            print("✅ Verified: Argos zh → en is ready")
            return True

        print("⚠️ Model installed but translator verification failed")
        return False

    except Exception as e:
        print(f"⚠️ Argos API installation failed: {type(e).__name__}: {e}")
        return False


# =========================================================
# FALLBACK DOWNLOAD FROM INDEX
# =========================================================

def install_using_index():
    print("📋 Trying official Argos index...")

    try:
        response = requests.get(
            ARGOS_INDEX_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30
        )

        print(f"🌐 Index HTTP: {response.status_code}")
        response.raise_for_status()

        packages = response.json()

        # Normalize package list
        if isinstance(packages, list):
            package_list = packages
        elif isinstance(packages, dict):
            package_list = []

            def collect_items(value):
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            package_list.append(item)
                        elif isinstance(item, list):
                            collect_items(item)
                elif isinstance(value, dict):
                    if "from_code" in value or "to_code" in value:
                        package_list.append(value)
                    for child in value.values():
                        if isinstance(child, (list, dict)):
                            collect_items(child)

            collect_items(packages)
        else:
            package_list = []

        # Find zh -> en
        package = None
        for item in package_list:
            if not isinstance(item, dict):
                continue
            if item.get("from_code") == "zh" and item.get("to_code") == "en":
                package = item
                break

        if not package:
            raise RuntimeError("zh → en package not found in Argos index")

        version = package.get("package_version", "unknown")
        print(f"📦 Found Argos zh → en version {version}")

        links = package.get("links", [])
        if isinstance(links, str):
            links = [links]

        if not links:
            raise RuntimeError("No download links found")

        package_path = os.path.join(
            tempfile.gettempdir(),
            "translate-zh_en.argosmodel"
        )

        for url in links:
            if not url or url.startswith("ipfs://"):
                continue

            print()
            print("📦 Downloading Argos zh → en model...")
            print(f"⬇️ URL: {url}")

            try:
                if os.path.exists(package_path):
                    try:
                        os.remove(package_path)
                    except Exception:
                        pass

                with requests.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                    stream=True,
                    timeout=(30, 180)
                ) as r:
                    print(f"🌐 HTTP: {r.status_code}")
                    r.raise_for_status()

                    total = int(r.headers.get("content-length", 0))
                    downloaded = 0

                    with open(package_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                percent = downloaded / total * 100
                                print(
                                    f"\r⬇️ {percent:6.1f}% ({downloaded / 1024 / 1024:.1f} MB)",
                                    end="",
                                    flush=True
                                )

                    print()

                if not os.path.exists(package_path):
                    raise RuntimeError("Package file missing")

                size = os.path.getsize(package_path)
                print(f"📦 Downloaded: {size / 1024 / 1024:.2f} MB")

                if size < (1024 * 1024):
                    raise RuntimeError("Package is too small")

                if not zipfile.is_zipfile(package_path):
                    raise RuntimeError("Downloaded file is not a valid Argos package")

                print("✅ Argos package verified")
                print(f"📦 Installing: {package_path}")

                argostranslate.package.install_from_path(package_path)
                print("✅ Argos model installed")

                translator = get_installed_zh_en()
                if translator:
                    print("✅ Verified: Argos zh → en is ready")
                    return True

                print("⚠️ Package installed but zh → en translator unavailable")

            except Exception as e:
                print(f"⚠️ Download/install failed: {type(e).__name__}: {e}")
                continue

        return False

    except Exception as e:
        print(f"⚠️ Argos index installation failed: {type(e).__name__}: {e}")
        return False


# =========================================================
# INSTALL ARGOS ZH -> EN
# =========================================================

def install_argos_model():
    print("🌐 Checking Argos Chinese → English model...")

    # FIRST: CHECK INSTALLED TRANSLATOR
    try:
        translator = get_installed_zh_en()
        if translator:
            print("✅ Argos zh → en already installed")
            return True
    except Exception as e:
        print(f"⚠️ Existing model check failed: {type(e).__name__}: {e}")

    # SECOND: ARGOS NATIVE API
    if install_using_argos_api():
        return True

    # THIRD: OFFICIAL INDEX FALLBACK
    print("➡️ Native Argos API unavailable.")
    print("➡️ Trying official package index...")

    if install_using_index():
        return True

    print("❌ Argos model installation failed")
    return False


# =========================================================
# GET ARGOS TRANSLATOR
# =========================================================

def get_argos_translator():
    languages = argostranslate.translate.get_installed_languages()

    from_lang = None
    to_lang = None

    for lang in languages:
        code = getattr(lang, "code", None)
        if code == "zh":
            from_lang = lang
        elif code == "en":
            to_lang = lang

    if not from_lang:
        raise RuntimeError("Chinese language model not installed")

    if not to_lang:
        raise RuntimeError("English language model not installed")

    try:
        translator = from_lang.get_translation(to_lang)
    except Exception as e:
        raise RuntimeError(f"Unable to get Argos zh → en translator: {e}")

    if not translator:
        raise RuntimeError("Argos zh → en translator not found")

    return translator


# =========================================================
# BROWSER FETCH
# =========================================================

async def fetch_html(url):
    print(f"🌐 Fetching: {safe_url(url)}")

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": BASE_URL,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                print(f"🌐 HTTP: {response.status}")
                response.raise_for_status()

                html = await response.text(encoding="utf-8", errors="ignore")
                print(f"✅ HTML: {len(html):,} bytes")

                DEBUG_HTML_FILE.write_text(html, encoding="utf-8")
                print(f"💾 HTML saved: {DEBUG_HTML_FILE}")

                return html

    except Exception as e:
        print(f"❌ Fetch error: {type(e).__name__}: {e}")
        return ""


# =========================================================
# CLEAN TITLE / TEAM NAME
# =========================================================

def clean_team_name(text):
    if not text:
        return ""

    text = str(text)

    # Normalisasi whitespace
    text = re.sub(r"\s+", " ", text)

    # Hapus tanda baca
    text = re.sub(r"""[,\.:;!?/\\|_\=\+\*\#@]""", " ", text)

    # Hapus tanda kurung / bracket
    text = re.sub(r"[\(\)\[\]\{\}]", " ", text)

    # Hapus tanda kutip
    text = re.sub(r"""["'`´]""", "", text)

    # Rapikan spasi lagi
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =========================================================
# TRANSLATE ONE NAME
# =========================================================

def translate_one(translator, text):
    text = text.strip()

    if not text:
        return ""

    # CACHE
    if text in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[text]

    # NON-CHINESE
    if not contains_chinese(text):
        TRANSLATION_CACHE[text] = text
        return text

    # ARGOS
    try:
        result = translator.translate(text)
        result = result.replace("\n", " ").strip()

        if result:
            TRANSLATION_CACHE[text] = result
            return result

    except Exception as e:
        print(f"⚠️ Argos failed '{text}': {e}")

    # FALLBACK ORIGINAL
    TRANSLATION_CACHE[text] = text
    return text


# =========================================================
# TRANSLATE ALL TEAMS
# =========================================================

async def translate_all_teams(team_names, translator):
    unique_names = list(
        dict.fromkeys(
            name.strip()
            for name in team_names
            if name and name.strip()
        )
    )

    print(f"🌐 Translating {len(unique_names)} unique team names locally...")

    result = {}

    # Argos is CPU-bound
    loop = asyncio.get_running_loop()

    for index, name in enumerate(unique_names, start=1):
        translated = await loop.run_in_executor(
            None,
            translate_one,
            translator,
            name
        )

        result[name] = translated
        print(f"[{index}/{len(unique_names)}] {name} -> {translated}")

        # SAVE CACHE
        if index % 25 == 0:
            save_translation_cache()

    save_translation_cache()

    print(f"✅ Translation completed: {len(result)} teams")
    return result


# =========================================================
# PARSE MATCHES
# =========================================================

async def parse_matches(html, translator):
    soup = BeautifulSoup(html, "html.parser")

    a_tags = soup.select("a.clearfix")

    if not a_tags:
        print("⚠️ No matches found")
        return []

    print(f"📺 Found {len(a_tags)} match elements")

    matches = []
    all_team_names = []

    # FIRST PASS
    for a_tag in a_tags:
        match_url = a_tag.get("href", "")
        if not match_url:
            continue

        match_id = match_url.rstrip("/").split("/")[-1]

        section = a_tag.find("section", class_="jiabifeng")
        if not section:
            continue

        # HOME
        home_div = section.find("div", class_="team zhudui")
        home_team = (
            home_div.p.get_text(strip=True)
            if home_div and home_div.p
            else ""
        )

        # AWAY
        away_div = section.find("div", class_="team kedui")
        away_team = (
            away_div.p.get_text(strip=True)
            if away_div and away_div.p
            else ""
        )

        if home_team:
            all_team_names.append(home_team)

        if away_team:
            all_team_names.append(away_team)

        # LEAGUE
        liga_name = ""
        event_time = ""

        center_div = section.find("div", class_="center")
        if center_div:
            liga_tag = center_div.find("p", class_="eventtime_wuy")
            if liga_tag:
                em = liga_tag.find("em")
                i = liga_tag.find("i")

                if em:
                    liga_name = em.get_text(strip=True)

                if i:
                    event_time = i.get_text(strip=True)

        # TIME
        data_time = a_tag.get("data-time", "")

        try:
            dt_obj = datetime.strptime(f"{data_time} {event_time}", "%Y-%m-%d %H:%M")
            dt_obj = dt_obj.replace(tzinfo=SHANGHAI)
            dt_obj = dt_obj.astimezone(JAKARTA)
            dt_str = dt_obj.strftime("%d/%m-%H.%M")

        except Exception as e:
            print(f"⚠️ Time error {data_time} {event_time}: {e}")
            dt_str = f"{data_time}-{event_time}"

        matches.append({
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "liga_name": liga_name,
            "dt_str": dt_str,
        })

    # TRANSLATE
    translations = await translate_all_teams(all_team_names, translator)

    # BUILD M3U
    lines = []

    for match in matches:
        home_team = translations.get(match["home_team"], match["home_team"])
        away_team = translations.get(match["away_team"], match["away_team"])

        # CLEAN TEAM NAMES
        home_team = clean_team_name(home_team)
        away_team = clean_team_name(away_team)

        # CLEAN LEAGUE
        liga_name = clean_team_name(match["liga_name"])

        # BUILD TITLE
        title = f"{home_team} vs {away_team}"

        # ADD LEAGUE ONLY IF NEEDED
        if liga_name:
            title = f"{title} ({liga_name})"

        # FINAL CLEAN
        title = re.sub(r"\s+", " ", title).strip()

        lines.append(
            f'#EXTINF:-1 '
            f'group-title="⚽️| LIVE EVENT" '
            f'tvg-logo="{LOGO_URL}", '
            f'{match["dt_str"]} '
            f'{title}'
        )

        lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        lines.append(f'#EXTVLCOPT:http-referrer={BASE_URL}')
        lines.append(f'{WORKER_URL}{match["match_id"]}')

    return lines


# =========================================================
# MAIN
# =========================================================

async def main():
    print("========================================")
    print("🚀 CHINZAKODOK")
    print("🌐 Browser + LOCAL Argos Translation")
    print("========================================")

    # INSTALL MODEL
    model_ok = install_argos_model()

    if not model_ok:
        print("❌ Argos model unavailable")
        return

    # GET TRANSLATOR
    try:
        translator = get_argos_translator()
    except Exception as e:
        print(f"❌ Translator initialization failed: {e}")
        return

    print("✅ Local zh → en translator ready")

    # FETCH HTML
    html = await fetch_html(TARGET_URL)

    if not html:
        print("❌ Failed to fetch HTML")
        return

    # PARSE
    lines = await parse_matches(html, translator)

    # WRITE M3U
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        if lines:
            f.write("\n".join(lines))

    # RESULT
    if lines:
        print("========================================")
        print(f"✅ Total matches: {len(lines) // 4}")
        print(f"💾 M3U: {OUTPUT_FILE.resolve()}")
        print(f"💾 Cache: {TRANSLATION_CACHE_FILE.resolve()}")
        print("========================================")
    else:
        print("⚠️ M3U kosong")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
