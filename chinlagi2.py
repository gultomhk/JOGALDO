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
    "南奔勇士": "Lamphun Warriors",
    "蒙通联": "Muangthong United",
    "东京电击": "Tokyo Electro",
    "宇都宫皇者": "Utsunomiya Kings",
}
LEAGUE_TRANSLATIONS = {
    "日职联": "Japan J1 League",
    "泰超": "Thai Premier League", 
    "日篮B1": "Japan B1 League",
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

def extract_matches_from_data(data):
    """Extract matches from various possible data structures"""
    matches = []
    
    if isinstance(data, list):
        # Data langsung berupa list matches
        matches = data
    elif isinstance(data, dict):
        # Cari di berbagai kemungkinan key
        possible_keys = ["list", "dataList", "matches", "data"]
        for key in possible_keys:
            if key in data and isinstance(data[key], list):
                matches.extend(data[key])
                break
        
        # Jika tidak ada key yang cocok, mungkin data本身就是match
        if not matches and any(k in data for k in ["hteam_name", "ateam_name", "id", "mid"]):
            matches = [data]
    
    return matches

def main():
    print("🚀 Fetching matches from API...")
    raw = fetch_matches()
    print("✅ Response received")

    if not isinstance(raw, dict):
        print(f"⚠️ Unexpected response type: {type(raw)}")
        return

    # Extract matches dari berbagai kemungkinan struktur
    matches = extract_matches_from_data(raw)
    
    # Jika ada key "data", coba extract dari sana juga
    if "data" in raw:
        data_matches = extract_matches_from_data(raw["data"])
        matches.extend(data_matches)

    # Hapus duplikat berdasarkan ID
    seen_ids = set()
    unique_matches = []
    for match in matches:
        match_id = match.get("id") or match.get("mid")
        if match_id and match_id not in seen_ids:
            seen_ids.add(match_id)
            unique_matches.append(match)

    print(f"📊 Found {len(unique_matches)} unique matches")

    if not unique_matches:
        print("⚠️ No matches found in API")
        print("🔍 Raw response keys:", raw.keys() if isinstance(raw, dict) else "N/A")
        return

    lines = []
    match_count = 0
    
    for match in unique_matches:
        try:
            # Cari ID dari berbagai kemungkinan field
            mid = match.get("mid") or match.get("id")
            if not mid:
                print(f"⚠️ Skipped match without ID: {match.get('hteam_name', 'Unknown')} vs {match.get('ateam_name', 'Unknown')}")
                continue

            urls = extract_urls(match)

            home = translate_text(match.get("hteam_name", ""), TEAM_TRANSLATIONS)
            away = translate_text(match.get("ateam_name", ""), TEAM_TRANSLATIONS)
            league = translate_text(match.get("name", ""), LEAGUE_TRANSLATIONS)
            logo = match.get("hteam_logo") or match.get("ateam_logo") or DEFAULT_LOGO

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
            match_count += 1

            # log tambahan
            status = match.get("status", 0)
            status_name = match.get("status_up_name", "")
            
            if urls:
                print(f"✅ [{match_count}] {mid}: {title} (live_urls: {len(urls)}, status: {status_name})")
            else:
                print(f"✅ [{match_count}] {mid}: {title} (no live_urls, worker only, status: {status_name})")

        except Exception as e:
            print(f"❌ Error parsing match {match.get('id') or 'Unknown'}: {e}")

    # tulis output
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.writelines(lines)

    print(f"✅ Playlist saved to {OUT_FILE} with {match_count} matches")
    
if __name__ == "__main__":
    main()
