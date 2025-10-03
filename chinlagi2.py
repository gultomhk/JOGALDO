import time
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


def fetch_matches(max_retries=3, backoff=5):
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

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"⚠️ Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                print(f"⏳ Retrying in {backoff} seconds...")
                time.sleep(backoff)
            else:
                print("❌ All retries failed.")
                raise


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


def format_time(matchtime):
    """Format waktu ke dd/mm-HH.MM, support berbagai format"""
    if not matchtime:
        return "??"

    # kalau angka (epoch timestamp)
    if isinstance(matchtime, int):
        try:
            dt = datetime.fromtimestamp(matchtime)
            return dt.strftime("%d/%m-%H.%M")
        except:
            return "??"

    if isinstance(matchtime, str):
        cleaned = matchtime.replace(" 21:0:0", " 21:00:00")  # perbaiki jam rusak
        for fmt in [
            "%Y-%m-%d %H:%M:%S",   # 2025-10-03 20:00:00
            "%Y/%m/%d %H:%M:%S",
            "%b %d, %Y %I:%M:%S %p",  # Oct 3, 2025 09:00:00 PM
            "%b %d, %Y %H:%M:%S %p",
        ]:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.strftime("%d/%m-%H.%M")
            except:
                continue
    return str(matchtime)


def get_match_status_text(match):
    """Get readable status text for match"""
    status = match.get("status", 1)
    status_name = str(match.get("status_up_name", "")).strip()

    if status == 0:  # Live match
        if status_name.isdigit():
            quarter = int(status_name)
            quarter_map = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4", 8: "Q4"}
            return f"LIVE {quarter_map.get(quarter, f'Q{quarter}')}"
        elif status_name in ["上半场", "下半场"]:
            cn_map = {"上半场": "1st Half", "下半场": "2nd Half"}
            return f"LIVE {cn_map.get(status_name, status_name)}"
        else:
            return f"LIVE {status_name}" if status_name else "LIVE"

    status_map = {0: "LIVE", 1: "UPCOMING", 2: "ENDED", 3: "POSTPONED"}
    return status_map.get(status, "UPCOMING")


def extract_all_matches(raw_data):
    """Extract semua matches dari struktur data yang kompleks"""
    all_matches = []
    
    def extract_from_dict(data_dict, path=""):
        matches = []
        if not isinstance(data_dict, dict):
            return matches

        # Cek jika ini langsung match object
        if any(k in data_dict for k in ["hteam_name", "ateam_name", "id", "mid"]):
            matches.append(data_dict)
            return matches

        # Cari di semua keys
        for key, value in data_dict.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        if any(k in item for k in ["hteam_name", "ateam_name", "id", "mid"]):
                            matches.append(item)
                        else:
                            matches.extend(extract_from_dict(item))
            elif isinstance(value, dict):
                matches.extend(extract_from_dict(value))
        return matches
    
    if isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, dict):
                all_matches.extend(extract_from_dict(item))
    elif isinstance(raw_data, dict):
        all_matches = extract_from_dict(raw_data)
    
    return all_matches


def main():
    print("🚀 Fetching matches from API...")
    raw = fetch_matches()
    print("✅ Response received")

    if not isinstance(raw, dict) or "data" not in raw:
        print("⚠️ Unexpected JSON structure:", raw.keys() if isinstance(raw, dict) else type(raw))
        return

    data = raw["data"]
    matches = extract_all_matches(data)

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

            status_text = get_match_status_text(match)
            title = f"{tstr} {home} vs {away} ({league}) [{status_text}]"

            worker_url = WORKER_TEMPLATE.format(id=mid)

            m3u_line = (
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{logo}",{title}\n'
                f'#EXTVLCOPT:http-user-agent={UA}\n'
                f'#EXTVLCOPT:http-referrer={REFERER}\n'
                f"{worker_url}\n"
            )
            lines.append(m3u_line)

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
