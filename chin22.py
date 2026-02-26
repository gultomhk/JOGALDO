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
# Translate Utility
# ==========================
translate_cache = {}
TARGET_LANG = "en"
LIBRE_URL = "https://libretranslate.de/translate"

def is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)

def to_pinyin(text: str) -> str:
    try:
        return " ".join(lazy_pinyin(text)).title()
    except:
        return text

def libre_translate(text: str, target=TARGET_LANG):
    try:
        payload = {
            "q": text,
            "source": "auto",
            "target": target,
            "format": "text"
        }
        r = requests.post(LIBRE_URL, data=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("translatedText")
    except:
        return None

def translate_text(text: str, target=TARGET_LANG) -> str:
    if not text:
        return ""
    text = text.strip()

    if not text or text.isnumeric() or is_ascii(text):
        return text

    if text in translate_cache:
        return translate_cache[text]

    # Layer 1: Google
    try:
        translated = GoogleTranslator(source="auto", target=target).translate(text)
        if translated:
            translate_cache[text] = translated
            return translated
    except:
        pass

    # Layer 2: LibreTranslate
    libre_result = libre_translate(text, target)
    if libre_result:
        translate_cache[text] = libre_result
        return libre_result

    # Layer 3: Pinyin
    pinyin_text = to_pinyin(text)
    translate_cache[text] = pinyin_text
    return pinyin_text

# ==========================
# Time Convert
# ==========================
def to_wib(utc_time_str):
    try:
        dt = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")
        dt_wib = dt + timedelta(hours=7)
        return dt_wib.strftime("%d/%m-%H.%M")
    except:
        return "00/00-00.00"

# ==========================
# Build Title
# ==========================
def build_title(event):
    home = translate_text(event.get("home", ""))
    away = translate_text(event.get("away", ""))
    title_raw = translate_text(event.get("title", ""))

    if home and away:
        return f"{home} VS {away}"

    if title_raw:
        return title_raw

    return "Live Event"

# ==========================
# Safe JSON Fetch
# ==========================
def safe_json_request(url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()
    except json.JSONDecodeError:
        print("❌ Response bukan JSON valid")
        return {}
    except Exception as e:
        print("❌ Request error:", e)
        return {}

# ==========================
# Main
# ==========================
def main():
    headers = {
        "User-Agent": USER_AGENT
    }

    if not URL:
        print("❌ URL kosong di config")
        return

    data = safe_json_request(URL, headers)
    events = data.get("events", [])

    if not events:
        print("⚠️ Tidak ada event ditemukan")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")

        for event in events:
            channels = event.get("channels", [])
            if not channels:
                continue

            channel_id = channels[0].get("id")
            if not channel_id:
                continue

            time_wib = to_wib(event.get("startTs", ""))
            match_title = build_title(event)

            comp = event.get("competition_en")
            if not comp:
                comp = translate_text(event.get("competition", ""))

            f.write(
                f'#EXTINF:-1 tvg-logo="{LOGO}" '
                f'group-title="⚽️| LIVE EVENT",{time_wib} {match_title} ({comp})\n'
            )

            if UAM3U:
                f.write(f'#EXTVLCOPT:http-user-agent={UAM3U}\n')

            f.write(f'{WORKER_URL}/index.m3u8?id={channel_id}\n\n')

    print("✅ CONGOR.m3u berhasil dibuat")

if __name__ == "__main__":
    main()
