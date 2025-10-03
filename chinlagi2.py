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
    "高华尤夫卡": "Kryvbas KR",
    "鲁克维尼基": "Rukh Vynnyky",
}
LEAGUE_TRANSLATIONS = {
    "日职联": "Japan J1 League",
    "泰超": "Thai Premier League", 
    "日篮B1": "Japan B1 League",
    "乌克超": "Ukrainian Premier League",
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
        "ps": 200,  # Increased to get more matches
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

def get_match_status_text(match):
    """Get readable status text for match"""
    status = match.get("status", 1)
    status_up = match.get("status_up", 1)
    status_name = match.get("status_up_name", "")
    
    # Status mapping
    status_map = {
        0: "LIVE",
        1: "UPCOMING", 
        2: "ENDED",
        3: "POSTPONED"
    }
    
    # Basketball quarter mapping
    quarter_map = {
        1: "Q1",
        2: "Q2", 
        3: "Q3",
        4: "Q4",
        8: "Q4"  # Sometimes 8 means Q4
    }
    
    if status == 0:  # Live match
        if status_name.isdigit():
            quarter = int(status_name)
            return f"LIVE {quarter_map.get(quarter, f'Q{quarter}')}"
        elif status_name in ["上半场", "下半场"]:
            return f"LIVE {status_name}"
        else:
            return "LIVE"
    
    return status_map.get(status, "UPCOMING")

def extract_all_matches(raw_data):
    """Extract semua matches dari struktur data yang kompleks"""
    all_matches = []
    
    def extract_from_dict(data_dict):
        matches = []
        # Cari key yang berisi list of matches
        for key, value in data_dict.items():
            if isinstance(value, list):
                # Cek jika ini list of matches (ada elemen dengan field match)
                for item in value:
                    if isinstance(item, dict):
                        if any(k in item for k in ["hteam_name", "ateam_name", "id", "mid"]):
                            matches.append(item)
            elif isinstance(value, dict):
                # Rekursif ke nested dict
                matches.extend(extract_from_dict(value))
        return matches
    
    if isinstance(raw_data, list):
        # Data langsung berupa list of matches
        for item in raw_data:
            if isinstance(item, dict) and any(k in item for k in ["hteam_name", "ateam_name", "id", "mid"]):
                all_matches.append(item)
    elif isinstance(raw_data, dict):
        all_matches = extract_from_dict(raw_data)
    
    return all_matches

def main():
    print("🚀 Fetching matches from API...")
    raw = fetch_matches()
    print("✅ Response received")

    if not isinstance(raw, dict):
        print(f"⚠️ Unexpected response type: {type(raw)}")
        return

    # Debug: print struktur data
    print(f"🔍 Raw data keys: {list(raw.keys())}")
    
    # Extract semua matches
    all_matches = extract_all_matches(raw)
    print(f"📊 Found {len(all_matches)} total matches in response")

    # Hapus duplikat berdasarkan ID
    seen_ids = set()
    unique_matches = []
    for match in all_matches:
        match_id = match.get("id") or match.get("mid")
        if match_id and match_id not in seen_ids:
            seen_ids.add(match_id)
            unique_matches.append(match)

    print(f"🎯 After deduplication: {len(unique_matches)} unique matches")

    if not unique_matches:
        print("⚠️ No matches found in API")
        return

    lines = []
    match_count = 0
    
    # Debug: Track specific match IDs
    target_ids = ["4362065", "3861747"]
    found_targets = []
    
    for match in unique_matches:
        try:
            # Cari ID dari berbagai kemungkinan field
            mid = match.get("mid") or match.get("id")
            if not mid:
                continue

            # Track target matches
            if str(mid) in target_ids:
                found_targets.append(str(mid))
                print(f"🎯 FOUND TARGET MATCH: {mid} - {match.get('hteam_name')} vs {match.get('ateam_name')}")
                print(f"   Status: {match.get('status')}, Status Name: {match.get('status_up_name')}")

            urls = extract_urls(match)

            home = translate_text(match.get("hteam_name", ""), TEAM_TRANSLATIONS)
            away = translate_text(match.get("ateam_name", ""), TEAM_TRANSLATIONS)
            league = translate_text(match.get("name", ""), LEAGUE_TRANSLATIONS)
            logo = match.get("hteam_logo") or match.get("ateam_logo") or DEFAULT_LOGO

            matchtime = match.get("matchtime") or match.get("matchtime_en")
            tstr = format_time(matchtime)

            # Get status text
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
            match_count += 1

            # log tambahan
            status = match.get("status", 0)
            status_name = match.get("status_up_name", "")
            
            if urls:
                print(f"✅ [{match_count}] {mid}: {home} vs {away} (live_urls: {len(urls)}, status: {status_text})")
            else:
                print(f"✅ [{match_count}] {mid}: {home} vs {away} (no live_urls, worker only, status: {status_text})")

        except Exception as e:
            print(f"❌ Error parsing match {match.get('id') or 'Unknown'}: {e}")

    # tulis output
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.writelines(lines)

    print(f"✅ Playlist saved to {OUT_FILE} dengan {match_count} matches")
    
    # Debug summary
    print(f"🔍 Target matches found: {found_targets}")
    missing_targets = [mid for mid in target_ids if mid not in found_targets]
    if missing_targets:
        print(f"❌ Missing target matches: {missing_targets}")
        print("🔍 Checking if missing matches exist in raw data...")
        for match in all_matches:
            match_id = str(match.get("id") or match.get("mid"))
            if match_id in missing_targets:
                print(f"   Found missing match {match_id} in raw data:")
                print(f"   {match.get('hteam_name')} vs {match.get('ateam_name')}")
                print(f"   Status: {match.get('status')}, Status Name: {match.get('status_up_name')}")
    
if __name__ == "__main__":
    main()
