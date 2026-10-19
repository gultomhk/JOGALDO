import asyncio
import json
import re

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Referer": BASE_URL,
    "Origin": BASE_URL.rstrip("/"),
}


# =========================================================
# ARGOS CONFIG
# =========================================================

ARGOS_FROM = "zh"
ARGOS_TO = "en"

ARGOS_CONCURRENCY = 4


# =========================================================
# SAFE URL  (dengan label)
# =========================================================

def safe_url(url, label=None):
    """
    Kembalikan string aman untuk log, ditandai dengan label.
    Tidak menampilkan scheme, host, path, query, atau fragment.

    Label otomatis:
      - gogo*      -> (gogourl)
      - github*    -> (argosurl)
      - argos*     -> (argosurl)
      - lainnya    -> (url)
    """
    try:
        if url is None:
            return f"({label})" if label else "[URL disembunyikan]"

        url_str = str(url).strip()
        if not url_str:
            return f"({label})" if label else "[URL disembunyikan]"

        p = urlparse(url_str)

        if not p.scheme or not p.netloc:
            return f"({label})" if label else "[URL disembunyikan]"

        host = (p.hostname or "").lower()

        if not label:
            if "gogo" in host:
                label = "gogourl"
            elif "github" in host or "githubusercontent" in host:
                label = "argosurl"
            elif "argos" in host:
                label = "argosurl"
            else:
                label = "url"

        return f"({label})"

    except Exception:
        return f"({label})" if label else "[URL disembunyikan]"


# =========================================================
# SAFE ERROR
# =========================================================

URL_REGEX = re.compile(r"https?://[^\s'\"<>\)\]]+")


def safe_error(e):
    """
    Kembalikan string error yang sudah di-mask URL-nya.
    """
    try:
        msg = str(e) if e is not None else ""
        msg = URL_REGEX.sub(
            lambda m: safe_url(m.group(0)),
            msg
        )
        name = type(e).__name__ if e is not None else "Error"
        if msg:
            return f"{name}: {msg}"
        return name
    except Exception:
        return "Error"


# =========================================================
# CACHE
# =========================================================

CACHE_FILE = Path(__file__).parent / "translation_cache.json"


def load_cache():
    if not CACHE_FILE.exists():
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception as e:
        print(f"⚠️ Cache read error: {safe_error(e)}")

    return {}


translation_cache = load_cache()


def save_cache():
    try:
        tmp_file = CACHE_FILE.with_suffix(".tmp")

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                translation_cache,
                f,
                ensure_ascii=False,
                indent=2
            )

        tmp_file.replace(CACHE_FILE)

    except Exception as e:
        print(f"⚠️ Cache save error: {safe_error(e)}")


# =========================================================
# CHINESE CHECK
# =========================================================

def contains_chinese(text):
    if not text:
        return False

    return any("\u4e00" <= c <= "\u9fff" for c in text)


# =========================================================
# CLEAN TEXT (parsing)
# =========================================================

def clean_text(text):
    if not text:
        return ""

    text = str(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# CLEAN TEAM / LEAGUE NAME (setelah translation)
# =========================================================

def clean_team_name(text):
    if not text:
        return ""

    text = str(text)

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"""[,\.:;!?/\\|_\=\+\*\#@]""", " ", text)
    text = re.sub(r"[\(\)\[\]\{\}]", " ", text)
    text = re.sub(r"""["'`´]""", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =========================================================
# ARGOS LANGUAGE
# =========================================================

def get_installed_languages():
    try:
        return argostranslate.translate.get_installed_languages()

    except Exception as e:
        print(f"⚠️ Failed to get Argos languages: {safe_error(e)}")
        return []


# =========================================================
# GET ARGOS TRANSLATOR
# =========================================================

def get_argos_translator():
    languages = get_installed_languages()

    from_lang = None
    to_lang = None

    for lang in languages:
        code = getattr(lang, "code", "")

        if code == ARGOS_FROM:
            from_lang = lang
        elif code == ARGOS_TO:
            to_lang = lang

    if not from_lang:
        raise RuntimeError(
            "Argos Chinese language model not installed"
        )

    if not to_lang:
        raise RuntimeError(
            "Argos English language model not installed"
        )

    try:
        translator = from_lang.get_translation(to_lang)

    except Exception as e:
        raise RuntimeError(
            f"Unable to get Argos translator: {safe_error(e)}"
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
    print()
    print("🌐 Checking Argos Chinese → English model...")

    # CHECK EXISTING
    try:
        translator = get_argos_translator()

        if translator:
            print("✅ Argos zh → en already installed")
            return translator

    except Exception:
        pass

    # LOAD PACKAGE LIST
    print("📋 Loading Argos package list...")

    try:
        packages = argostranslate.package.get_available_packages()

    except Exception as e:
        print(f"❌ Failed to load Argos packages: {safe_error(e)}")
        return None

    if not packages:
        print("❌ Argos package list empty")
        return None

    print(f"📦 Available packages: {len(packages)}")

    # FIND ZH → EN
    selected = None

    for package in packages:
        from_code = getattr(package, "from_code", "")
        to_code = getattr(package, "to_code", "")

        if from_code == "zh" and to_code == "en":
            selected = package
            break

    if selected is None:
        print("❌ Argos zh → en package not found")
        return None

    version = getattr(selected, "package_version", "unknown")
    print(f"📦 Found Argos zh → en version {version}")

    # DOWNLOAD
    try:
        print("📦 Downloading Argos zh → en model...")

        package_path = selected.download()

        # Jangan tampilkan path mentah
        print("📦 Package downloaded")

        print("📦 Installing Argos model...")
        argostranslate.package.install_from_path(package_path)
        print("✅ Argos model installed")

    except Exception as e:
        print(f"❌ Argos installation failed: {safe_error(e)}")
        return None

    # VERIFY
    try:
        translator = get_argos_translator()

        if translator:
            print("✅ Verified: Argos zh → en is ready")
            return translator

    except Exception as e:
        print(f"❌ Argos verification failed: {safe_error(e)}")

    return None


# =========================================================
# ARGOS TRANSLATE ONE
# =========================================================

def translate_sync(translator, text):
    text = text.strip()

    if not text:
        return ""

    # CACHE
    if text in translation_cache:
        return translation_cache[text]

    # NO CHINESE
    if not contains_chinese(text):
        translation_cache[text] = text
        return text

    # ARGOS
    try:
        translated = translator.translate(text)

        if translated:
            translated = str(translated).replace("\n", " ").strip()

            if translated:
                translation_cache[text] = translated
                return translated

    except Exception as e:
        print(f"⚠️ Argos failed: {safe_error(e)}")

    # FALLBACK
    translation_cache[text] = text
    return text


# =========================================================
# ASYNC TRANSLATE ONE
# =========================================================

async def translate_one(translator, text, semaphore):
    async with semaphore:
        result = await asyncio.to_thread(
            translate_sync,
            translator,
            text
        )

        return (text, result)


# =========================================================
# TRANSLATE ALL
# =========================================================

async def translate_all(texts, translator):
    unique_texts = list(
        dict.fromkeys(
            x.strip()
            for x in texts
            if x and x.strip()
        )
    )

    need_translation = [
        x
        for x in unique_texts
        if (
            x not in translation_cache
            and contains_chinese(x)
        )
    ]

    print()
    print(f"📦 Total unique names: {len(unique_texts)}")
    print(f"📦 Need translation: {len(need_translation)}")

    if not need_translation:
        print("✅ Semua nama sudah ada di cache")

        return {
            x: translation_cache.get(x, x)
            for x in unique_texts
        }

    print()
    print(
        f"🚀 Translating {len(need_translation)} "
        f"names with local Argos..."
    )
    print(f"⚙️ Parallel workers: {ARGOS_CONCURRENCY}")

    semaphore = asyncio.Semaphore(ARGOS_CONCURRENCY)

    tasks = [
        translate_one(translator, text, semaphore)
        for text in need_translation
    ]

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )

    completed = 0

    for item in results:
        if isinstance(item, Exception):
            print(f"⚠️ Worker error: {safe_error(item)}")
            continue

        text, translated = item

        translation_cache[text] = translated
        completed += 1

        print(
            f"[{completed}/{len(need_translation)}] "
            f"{text} → {translated}"
        )

        if completed % 25 == 0:
            save_cache()
            print(f"💾 Cache saved: {completed}")

    save_cache()

    print()
    print(
        f"✅ Translation finished: "
        f"{completed}/{len(need_translation)}"
    )

    return {
        x: translation_cache.get(x, x)
        for x in unique_texts
    }


# =========================================================
# DECODE HTML
# =========================================================

def decode_html(raw):
    encodings = ["utf-8", "gb18030", "gbk", "gb2312", "big5"]

    for enc in encodings:
        try:
            decoded = raw.decode(enc)

            if any(
                x in decoded
                for x in ["直播", "足球", "联赛", "女", "队", "VS"]
            ):
                print(f"✅ Decoded with: {enc}")
                return decoded

        except Exception:
            pass

    try:
        return raw.decode("utf-8", errors="ignore")

    except Exception:
        return ""


# =========================================================
# FETCH HTML - SMART RETRY + DIAGNOSTIC
# =========================================================

async def fetch_html(url):
    if not url or not str(url).strip():
        print("❌ BASE_URL kosong. Periksa gogodattvdata_file.txt")
        return ""

    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        print("❌ BASE_URL tidak valid. Harus menggunakan HTTP/HTTPS.")
        return ""

    # HTTPS tetap menjadi prioritas.
    candidates = [url.strip()]

    # Alternatif HTTP hanya jika URL awal HTTPS.
    if parsed.scheme == "https":
        candidates.append(
            urlunparse(parsed._replace(scheme="http"))
        )

    # Alternatif tanpa www.
    if parsed.hostname.startswith("www."):
        for candidate in list(candidates):
            p = urlparse(candidate)
            netloc = p.hostname[4:]

            if p.port:
                netloc += f":{p.port}"

            candidates.append(
                urlunparse(p._replace(netloc=netloc))
            )

    # Hilangkan duplikat tanpa mengubah urutan.
    candidates = list(dict.fromkeys(candidates))

    max_retries = 2
    timeout_seconds = 30

    for attempt in range(1, max_retries + 1):
        print()
        print(f"🔄 Fetch attempt {attempt}/{max_retries}")

        for index, test_url in enumerate(candidates, start=1):
            print(
                f"🌐 Fetching [{index}/{len(candidates)}]: "
                f"{safe_url(test_url, 'gogourl')}"
            )

            try:
                # Jalankan request dalam thread agar event loop
                # asyncio tidak terblokir.
                response = await asyncio.to_thread(
                    requests.get,
                    test_url,
                    headers=HEADERS,
                    impersonate="chrome",
                    timeout=timeout_seconds,
                    verify=True,
                    allow_redirects=True,
                )

                status = response.status_code
                raw = response.content
                byte_count = len(raw)

                print(f"📡 HTTP Status: {status}")
                print(f"📦 Response bytes: {byte_count:,}")

                print(
                    "🔗 Final URL: "
                    f"{safe_url(str(response.url), 'gogourl')}"
                )

                if status != 200:
                    print(
                        f"⚠️ HTTP {status}; "
                        "mencoba alamat berikutnya."
                    )
                    continue

                if not raw:
                    print("⚠️ Respons kosong.")
                    continue

                html = decode_html(raw)

                print(
                    f"📄 HTML length: {len(html):,} characters"
                )

                if len(html.strip()) < 1000:
                    print(
                        "⚠️ HTML terlalu pendek; "
                        "mencoba alamat berikutnya."
                    )
                    continue

                debug_file = (
                    Path(__file__).parent / "original_debug.html"
                )

                debug_file.write_text(
                    html,
                    encoding="utf-8"
                )

                print("✅ HTML fetch success")
                print("💾 Debug HTML: original_debug.html")

                return html

            except Exception as e:
                error_text = str(e).lower()
                error_name = type(e).__name__

                if (
                    "timeout" in error_text
                    or "timed out" in error_text
                    or "curl: (28)" in error_text
                ):
                    print(
                        f"⏱️ Timeout ({error_name}); "
                        "mencoba alamat berikutnya."
                    )

                elif (
                    "resolve" in error_text
                    or "could not resolve" in error_text
                    or "name or service not known" in error_text
                ):
                    print(
                        f"🌐 DNS gagal ({error_name}); "
                        "alamat berikutnya akan dicoba."
                    )

                elif (
                    "ssl" in error_text
                    or "certificate" in error_text
                    or "tls" in error_text
                ):
                    print(
                        f"🔒 TLS/SSL gagal ({error_name}); "
                        "periksa sertifikat dan koneksi server."
                    )

                else:
                    # Jangan tampilkan URL atau detail sensitif.
                    print(
                        f"❌ Fetch error ({error_name}); "
                        f"detail: {safe_error(e)}"
                    )

        if attempt < max_retries:
            delay = 3
            print(
                f"⏳ Semua alamat gagal pada percobaan ini. "
                f"Retry dalam {delay} detik..."
            )
            await asyncio.sleep(delay)

    print("❌ Semua percobaan fetch gagal.")
    return ""


# =========================================================
# PARSE MATCHES
# =========================================================

async def parse_matches(html, translator):
    soup = BeautifulSoup(html, "html.parser")

    lines = []

    a_tags = soup.find_all(
        "a",
        href=lambda x: x and "/detail/" in x
    )

    print()
    print(f"📺 Found possible matches: {len(a_tags)}")

    if not a_tags:
        print("⚠️ No matches found.")
        return lines

    parsed_ids = set()
    matches = []

    # =====================================================
    # FIRST PASS
    # =====================================================

    for a_tag in a_tags:
        try:
            match_url = a_tag.get("href", "").strip()

            if not match_url:
                continue

            match_id = match_url.rstrip("/").split("/")[-1]

            if match_id in parsed_ids:
                continue

            parsed_ids.add(match_id)

            # HOME TEAM
            home_team = ""

            home_div = a_tag.find("div", class_="team zhudui")

            if home_div:
                p = home_div.find("p")

                if p:
                    home_team = clean_text(p.get_text(strip=True))

            # AWAY TEAM
            away_team = ""

            away_div = a_tag.find("div", class_="team kedui")

            if away_div:
                p = away_div.find("p")

                if p:
                    away_team = clean_text(p.get_text(strip=True))

            if not home_team and not away_team:
                continue

            # LEAGUE + TIME
            liga_name = ""
            event_time = ""

            center_div = a_tag.find("div", class_="center")

            if center_div:
                liga_tag = center_div.find(
                    "p", class_="eventtime_wuy"
                )

                if liga_tag:
                    em = liga_tag.find("em")
                    i_tag = liga_tag.find("i")

                    if em:
                        liga_name = clean_text(
                            em.get_text(strip=True)
                        )

                    if i_tag:
                        event_time = clean_text(
                            i_tag.get_text(strip=True)
                        )

            print(
                f"RAW: {home_team} vs {away_team} ({liga_name})"
            )

            matches.append({
                "match_id": match_id,
                "home_team": home_team,
                "away_team": away_team,
                "liga_name": liga_name,
                "event_time": event_time,
                "data_time": a_tag.get("data-time", "").strip(),
            })

        except Exception as e:
            print(f"⚠️ Parse match error: {safe_error(e)}")

    # =====================================================
    # COLLECT ALL NAMES
    # =====================================================

    all_names = []

    for match in matches:
        all_names.append(match["home_team"])
        all_names.append(match["away_team"])
        all_names.append(match["liga_name"])

    # =====================================================
    # TRANSLATE ALL
    # =====================================================

    translations = await translate_all(all_names, translator)

    # =====================================================
    # BUILD M3U
    # =====================================================

    for match in matches:
        home_team_en = translations.get(
            match["home_team"], match["home_team"]
        )
        away_team_en = translations.get(
            match["away_team"], match["away_team"]
        )
        liga_name_en = translations.get(
            match["liga_name"], match["liga_name"]
        )

        # CLEAN SETELAH TRANSLATE
        home_team_en = clean_team_name(home_team_en)
        away_team_en = clean_team_name(away_team_en)
        liga_name_en = clean_team_name(liga_name_en)

        # TIME
        try:
            dt_obj = datetime.strptime(
                f'{match["data_time"]} {match["event_time"]}',
                "%Y-%m-%d %H:%M"
            )

            dt_obj = dt_obj.replace(tzinfo=SHANGHAI)
            dt_obj = dt_obj.astimezone(JAKARTA)

            dt_str = dt_obj.strftime("%d/%m-%H.%M")

        except Exception as e:
            print(f"⚠️ Time parse error: {safe_error(e)}")

            dt_str = (
                f'{match["data_time"]} {match["event_time"]}'
            )

        # TITLE
        title = f"{home_team_en} vs {away_team_en}"

        if liga_name_en:
            title += f" ({liga_name_en})"

        # M3U
        lines.append(
            f'#EXTINF:-1 '
            f'group-title="⚽️| LIVE EVENT" '
            f'tvg-logo="{LOGO_URL}",'
            f'{dt_str} {title}'
        )

        lines.append(
            f'#EXTVLCOPT:http-user-agent={USER_AGENT}'
        )

        lines.append(
            f'#EXTVLCOPT:http-referrer={BASE_URL}'
        )

        lines.append(
            f"{WORKER_URL}{match['match_id']}"
        )

        print(f"✅ Parsed: {title}")

    return lines


# =========================================================
# MAIN
# =========================================================

async def main():
    print("========================================")
    print("🚀 GOGODATV")
    print("🌐 LOCAL ARGOS TRANSLATION")
    print("🧹 CLEAN AFTER TRANSLATION")
    print("========================================")

    # INSTALL / LOAD ARGOS
    translator = install_argos_model()

    if not translator:
        print("❌ Argos translator unavailable")
        return

    print("✅ Local zh → en translator ready")

    # FETCH
    html = await fetch_html(TARGET_URL)

    if not html:
        print("❌ Failed to fetch HTML. Exiting.")
        return

    print(f"📄 HTML length: {len(html):,}")

    # PARSE
    lines = await parse_matches(html, translator)

    # WRITE M3U
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        if lines:
            f.write("\n".join(lines))

    # RESULT
    print()
    print("========================================")

    if lines:
        print(f"✅ Total matches: {len(lines) // 4}")
        print(f"💾 M3U: {OUTPUT_FILE.resolve()}")
        print(f"💾 Cache: {CACHE_FILE.resolve()}")

    else:
        print("⚠️ No valid matches found.")
        print(f"💾 Empty M3U: {OUTPUT_FILE.resolve()}")

    print("========================================")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
