from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from deep_translator import GoogleTranslator

# Load konfigurasi dari file
CONFIG_FILE = Path.home() / "926data_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

config = load_config(CONFIG_FILE)

BASE_URL = config.get("BASE_URL", "")
LOGO_URL = config.get("LOGO_URL", "")
WORKER_URL = config.get("WORKER_URL", "")
USER_AGENT = config.get("USER_AGENT", "Mozilla/5.0")
REFERRER = config.get("REFERRER", "")

INPUT_FILE = "926page_source.html"

with open(INPUT_FILE, encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
translator = Translator()

def translate_zh_to_en(text):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='zh-CN', target='en').translate(text)
    except Exception as e:
        print("Translate error:", e)
        return text

lines = []

for a in soup.find_all("a", href=True):
    if a["href"].startswith("/bofang/"):
        slug_url = BASE_URL + a["href"]

        home_team_tag = a.select_one(".team.zhudui p")
        away_team_tag = a.select_one(".team.kedui p")
        event_name_tag = a.select_one(".eventtime em")
        event_time_tag = a.select_one(".eventtime i")

        home_team = home_team_tag.get_text(strip=True) if home_team_tag else "Home"
        away_team = away_team_tag.get_text(strip=True) if away_team_tag else "Away"
        event_name = event_name_tag.get_text(strip=True) if event_name_tag else ""
        event_time = event_time_tag.get_text(strip=True) if event_time_tag else "00:00"

        # Translate teks dari Chinese ke English
        home_team_en = translate_zh_to_en(home_team)
        away_team_en = translate_zh_to_en(away_team)
        event_name_en = translate_zh_to_en(event_name)

        date_attr = a.get("nzw-o-t", "").strip()
        datetime_str = f"{date_attr} {event_time}" if date_attr else ""

        try:
            if datetime_str:
                dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                # Asumsi waktu di web adalah CST (UTC+8)
                # Konversi ke WIB (UTC+7) = kurangi 1 jam
                dt_obj_wib = dt_obj - timedelta(hours=1)
                date_str = dt_obj_wib.strftime("%d/%m-%H.%M")
            else:
                date_str = "??/??-??.??"
        except Exception as e:
            print("Error parsing date:", e)
            date_str = datetime_str or "??/??-??.??"

        title = f"{date_str}  {home_team_en} vs {away_team_en} - {event_name_en}"

        lines.append(f'#EXTINF:-1 tvg-logo="{LOGO_URL}" group-title="⚽️| LIVE EVENT",{title}')
        lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        lines.append(f'#EXTVLCOPT:http-referrer={REFERRER}')

        id_only = slug_url.rstrip("/").split("/")[-1]  # ambil id terakhir (misal "1059")
        lines.append(f"{WORKER_URL}{id_only}")
        lines.append("")

OUTPUT_FILE = "926events.m3u"
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    f.write("\n".join(lines))

print(f"✅ Playlist berhasil dibuat: {OUTPUT_FILE} (total {len(lines)//5} event)")
