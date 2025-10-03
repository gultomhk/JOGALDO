import requests
from datetime import datetime
from pathlib import Path
import pytz
from deep_translator import GoogleTranslator

# ==========================
# Translator setup
# ==========================
translator = GoogleTranslator(source="auto", target="en")

# ==========================
# Load Config
# ==========================
CHINLAGI2DATA_FILE = Path.home() / "chinlagi2data_file.txt"

config_vars = {}
with open(CHINLAGI2DATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

UA = config_vars.get("UA")
REFERER = config_vars.get("REFERER")
WORKER_TEMPLATE = config_vars.get("WORKER_TEMPLATE")
DEFAULT_LOGO = config_vars.get("DEFAULT_LOGO")
BASE_URL = config_vars.get("BASE_URL")

OUT_FILE = "CHIN2_matches.m3u"

# ==========================
# Constants
# ==========================
TEAM_TRANSLATIONS = {
    "湘南丽海": "Shonan Bellmare",
    "东京绿茵": "Tokyo Verdy",
}
LEAGUE_TRANSLATIONS = {
    "日职联": "Japan J1 League",
}

HEADERS = {
    "User-Agent": UA,
    "Referer": REFERER,
    "Accept": "application/json, text/plain, */*",
}

# ==========================
# Functions
# ==========================
def get_today_date():
    tz = pytz.timezone("Asia/Bangkok")
    return datetime.now(tz).strftime("%Y-%m-%d")

def fetch_matches():
    params = {
        "isfanye": 1,
        "type": 0,
        "cid": 0,
        "ishot": 1,
        "pn": 1,
        "ps": 100,
        "level": "",
        "name": "",
        "langtype": "zh",
        "starttime": get_today_date(),
        "pid": 4,
        "zoneId": "Asia/Bangkok",
        "zhuboType": 1,
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def translate_text(text: str, dictionary: dict):
    if not text:
        return ""
    if text in dictionary:
        return dictionary[text]
    try:
        return translator.translate(text)
    except Exception:
        return text

def extract_urls(match: dict):
    urls = []
    for key in ["live_urls", "mirror_live_urls", "global_live_urls"]:
        if key in match and isinstance(match[key], list):
            for u in match[key]:
                if isinstance(u, dict) and u.get("url"):
                    urls.append(u.get("url"))
    return urls


def format_time(matchtime: str) -> str:
    """Format waktu ke dd/mm-HH.MM, fallback ke raw string kalau gagal parse"""
    if not matchtime:
        return "??"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%b %d, %Y %H:%M:%S %p"):
        try:
            dt = datetime.strptime(matchtime, fmt)
            return dt.strftime("%d/%m-%H.%M")
        except ValueError:
            continue
    return matchtime  # fallback


def main():
    print("🚀 Fetching matches from API...")
    raw = fetch_matches()
    print("✅ Response received")

    if not isinstance(raw, dict) or "data" not in raw:
        print("⚠️ Unexpected JSON structure:", raw.keys() if isinstance(raw, dict) else type(raw))
        return

    data = raw["data"]

    # cari list pertandingan
    matches = []
    if isinstance(data, list):
        matches = data
    elif isinstance(data, dict):
        if "list" in data and isinstance(data["list"], list):
            matches = data["list"]
        elif "dataList" in data and isinstance(data["dataList"], list):
            matches = data["dataList"]

    print(f"📊 Found {len(matches)} matches")

    if not matches:
        print("⚠️ No matches found in API")
        return

    lines = []
    for match in matches:
        try:
            mid = match.get("mid") or match.get("id")
            if not mid:
                print(f"⚠️ Skipped match without ID: {match}")
                continue

            urls = extract_urls(match)

            home = translate_text(match.get("hteam_name", ""), TEAM_TRANSLATIONS)
            away = translate_text(match.get("ateam_name", ""), TEAM_TRANSLATIONS)
            league = translate_text(match.get("name", ""), LEAGUE_TRANSLATIONS)
            logo = match.get("hteam_logo") or DEFAULT_LOGO

            matchtime = match.get("matchtime") or match.get("matchtime_en")
            tstr = format_time(matchtime)

            title = f"{tstr} {home} vs {away} ({league})"

            worker_url = WORKER_TEMPLATE.format(id=mid)

            m3u_line = (
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{logo}",{title}\n'
                f'#EXTVLCOPT:http-user-agent={UA}\n'
                f'#EXTVLCOPT:http-referrer={REFERER}\n'
                f"{worker_url}\n"
            )
            lines.append(m3u_line)

            # log tambahan
            if urls:
                print(f"✅ Added match {mid}: {title} (live_urls found)")
            else:
                print(f"✅ Added match {mid}: {title} (no live_urls, worker only)")

        except Exception as e:
            print(f"❌ Error parsing match {match.get('id') or match}: {e}")

    # tulis output
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.writelines(lines)

    print(f"✅ Playlist saved to {OUT_FILE}")
    
if __name__ == "__main__":
    main()
