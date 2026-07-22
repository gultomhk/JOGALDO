import requests
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from pathlib import Path
from pypinyin import lazy_pinyin
import json

# ==========================
# Load Config
# ==========================
CONGORDATA_FILE = Path.home() / "congordata_file.txt"

def load_config():
    config = {}

    if not CONGORDATA_FILE.exists():
        raise FileNotFoundError(f"{CONGORDATA_FILE} tidak ditemukan!")

    with open(CONGORDATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or "=" not in line:
                continue

            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()

    return config


config = load_config()

USER_AGENT = config.get("User-Agent", "Mozilla/5.0")
UAM3U = config.get("UAM3U", "")
WORKER_URL = config.get("WORKER_URL", "").rstrip("/")
LOGO = config.get("logo", "")
URL = config.get("URL", "")

OUTPUT_FILE = "CONGOR.m3u"

# ==========================
# Translate
# ==========================
translate_cache = {}

TARGET_LANG = "en"

LIBRE_URL = "https://libretranslate.de/translate"


def is_ascii(s):
    return all(ord(c) < 128 for c in s)


def to_pinyin(text):
    try:
        return " ".join(lazy_pinyin(text)).title()
    except:
        return text


def libre_translate(text, target=TARGET_LANG):
    try:
        r = requests.post(
            LIBRE_URL,
            data={
                "q": text,
                "source": "auto",
                "target": target,
                "format": "text"
            },
            timeout=10
        )

        r.raise_for_status()

        return r.json().get("translatedText")

    except:
        return None


def translate_text(text, target=TARGET_LANG):

    if not text:
        return ""

    text = text.strip()

    if text == "":
        return ""

    if text in translate_cache:
        return translate_cache[text]

    if is_ascii(text):
        return text

    try:
        result = GoogleTranslator(
            source="auto",
            target=target
        ).translate(text)

        if result:
            translate_cache[text] = result
            return result

    except:
        pass

    result = libre_translate(text, target)

    if result:
        translate_cache[text] = result
        return result

    result = to_pinyin(text)

    translate_cache[text] = result

    return result


# ==========================
# Time
# ==========================
def to_wib(time_str):
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
        dt += timedelta(hours=7)
        return dt.strftime("%d/%m-%H.%M")
    except:
        return "00/00-00.00"


# ==========================
# Build Title
# ==========================
def build_title(event):

    home = (
        event.get("home_en")
        or translate_text(event.get("home", ""))
    ).strip()

    away = (
        event.get("away_en")
        or translate_text(event.get("away", ""))
    ).strip()

    if home and away:
        return f"{home} VS {away}"

    title = (
        event.get("title_en")
        or translate_text(event.get("title", ""))
    ).strip()

    if title:
        return title

    return "Live Event"


# ==========================
# Fetch JSON
# ==========================
def safe_json_request(url, headers):

    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        r.raise_for_status()

        return r.json()

    except json.JSONDecodeError:
        print("❌ Response bukan JSON")
        return {}

    except Exception as e:
        print(e)
        return {}


# ==========================
# Main
# ==========================
def main():

    if not URL:
        print("URL kosong.")
        return

    headers = {
        "User-Agent": USER_AGENT
    }

    data = safe_json_request(URL, headers)

    events = data.get("events", [])

    print("Total event:", len(events))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

        f.write("#EXTM3U\n\n")

        for event in events:

            channels = event.get("channels", [])

            if not channels:
                continue

            channel = channels[0]

            stream_id = str(channel.get("id", "")).strip()

            if not stream_id:
                continue

            time_wib = to_wib(event.get("startTs", ""))

            title = build_title(event)

            comp = (
                event.get("competition_en")
                or translate_text(event.get("competition", ""))
            )

            f.write(
                f'#EXTINF:-1 tvg-logo="{LOGO}" '
                f'group-title="⚽️| LIVE EVENT",{time_wib} {title} ({comp})\n'
            )

            if UAM3U:
                f.write(
                    f"#EXTVLCOPT:http-user-agent={UAM3U}\n"
                )

            stream_url = (
                f"{WORKER_URL}/stream/{stream_id}/index.m3u8"
            )

            f.write(stream_url + "\n\n")

    print("✅ CONGOR.m3u berhasil dibuat")


if __name__ == "__main__":
    main()
