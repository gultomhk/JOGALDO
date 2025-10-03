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
WORKER_TEMPLATE = config_vars.get("WORKER_TEMPLATE")  #
DEFAULT_LOGO = config_vars.get("DEFAULT_LOGO")
BASE_URL = config_vars.get("BASE_URL")  # 

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
        "langtype": "id",
        "starttime": get_today_date(),
        "pid": 4,
        "zoneId": "Asia/Bangkok",
        "zhuboType": 1,
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def format_time(matchtime: str):
    dt = datetime.strptime(matchtime, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%d/%m-%H.%M")

def translate_text(text: str, dictionary: dict):
    if not text:
        return ""
    if text in dictionary:
        return dictionary[text]
    try:
        return translator.translate(text)
    except Exception:
        return text

def main():
    data = fetch_matches()
    if "data" not in data:
        print("⚠️ Unexpected JSON structure:", data.keys())
        return

    # Auto detect struktur
    matches = []
    if isinstance(data["data"], dict):
        if "list" in data["data"]:
            matches = data["data"]["list"]
        elif "dataList" in data["data"]:
            matches = data["data"]["dataList"]

    if not matches:
        print("⚠️ No matches found in API")
        return

    lines = []
    for match in matches:
        try:
            mid = match.get("id")
            if not mid:
                continue

            home = translate_text(match.get("hteam_name", ""), TEAM_TRANSLATIONS)
            away = translate_text(match.get("ateam_name", ""), TEAM_TRANSLATIONS)
            league = translate_text(match.get("name", ""), LEAGUE_TRANSLATIONS)

            # pakai logo tim kalau ada, fallback ke default
            logo = match.get("hteam_logo") or DEFAULT_LOGO

            matchtime = match.get("matchtime")
            if not matchtime:
                continue
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

        except Exception as e:
            print("Error parsing match:", e)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.writelines(lines)

    print(f"✅ Playlist saved to {OUT_FILE}")
