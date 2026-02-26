import requests
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from pathlib import Path

# ==========================
# Load Config dari congordata_file.txt
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
WORKER_URL = config.get("WORKER_URL", "")
LOGO = config.get("logo", "")
URL = config.get("URL", "")

OUTPUT_FILE = "CONGOR.m3u"

# ==========================
# Translate Utility
# ==========================
translate_cache = {}
TARGET_LANG = "en"  # bisa ganti ke id, ms, dll

def is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)

def translate_text(text: str, target=TARGET_LANG) -> str:
    if not text or text.isnumeric() or is_ascii(text):
        return text

    if text in translate_cache:
        return translate_cache[text]

    try:
        translated = GoogleTranslator(source="auto", target=target).translate(text)
        translate_cache[text] = translated
        return translated
    except Exception as e:
        print("⚠️ Translate error:", e, "=> pakai teks asli")
        return text

# ==========================
# Time Convert
# ==========================
def to_wib(utc_time_str):
    dt = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")
    dt_wib = dt + timedelta(hours=7)
    return dt_wib.strftime("%d/%m-%H.%M")

# ==========================
# Build Title
# ==========================
def build_title(event):
    home = translate_text(event.get("home", "").strip())
    away = translate_text(event.get("away", "").strip())
    title_raw = translate_text(event.get("title", "").strip())

    if home and away:
        return f"{home} VS {away}"

    if title_raw:
        return title_raw

    return "Live Event"

# ==========================
# Main
# ==========================
def main():
    headers = {
        "User-Agent": USER_AGENT
    }

    r = requests.get(URL, headers=headers, timeout=15)
    r.raise_for_status()

    data = r.json()
    events = data.get("events", [])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")

        for event in events:
            channels = event.get("channels", [])
            if not channels:
                continue

            channel_id = channels[0]["id"]
            time_wib = to_wib(event["startTs"])
            match_title = build_title(event)
            comp = event.get("competition_en") or translate_text(event.get("competition", ""))

            f.write(
                f'#EXTINF:-1 tvg-logo="{LOGO}" '
                f'group-title="⚽️| LIVE EVENT",{time_wib} {match_title} ({comp})\n'
            )

            if UAM3U:
                f.write(f'#EXTVLCOPT:http-user-agent={UAM3U}\n')

            f.write(f'{WORKER_URL}/index.m3u8?id={channel_id}\n\n')

    print("✅ CONGOR.m3u berhasil dibuat dengan translate cache")

if __name__ == "__main__":
    main()
