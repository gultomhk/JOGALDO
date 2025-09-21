import json
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

# ==========================
# Load Config dari congordata_file.txt
# ==========================
CONGORDATA_FILE = Path.home() / "congordata_file.txt"

config = {}
with open(CONGORDATA_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            # Jika value adalah list Python, gunakan eval
            if val.startswith("[") and val.endswith("]"):
                try:
                    config[key] = eval(val)
                except Exception:
                    config[key] = val
            # Jika string pakai kutip
            elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                config[key] = val.strip('"\'')
            else:
                config[key] = val

# Ambil variabel dari config
UA = config.get("UA")
REFERRER = config.get("REFERRER")
WORKER_URL = config.get("WORKER_URL")
logo = config.get("logo")
urls = config.get("urls", [])

# ==========================
# Translate Utility
# ==========================
translate_cache = {}
TARGET_LANG = "en"  # ganti 

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

def clean_title(title: str) -> str:
    title = title.replace("vs.", "vs")
    title = title.replace(",", " ")
    title = re.sub(r"\s+", " ", title)
    return title.strip()

# ==========================
# Ambil data anchor (__NEXT_DATA__)
# ==========================
anchors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent=UA)
    page = context.new_page()

    for url in urls:
        print(f"🌍 Load {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        script = page.query_selector("#__NEXT_DATA__")
        if script:
            try:
                raw_json = script.inner_text()
                data = json.loads(raw_json)
                records = data["props"]["pageProps"]["liveAnchorList"]["records"]
                anchors.extend(records)
            except Exception as e:
                print("⚠️ Error parse __NEXT_DATA__:", e)

    browser.close()

print(f"📊 Jumlah anchor ditemukan: {len(anchors)}")

# ==========================
# Build M3U
# ==========================
lines = ["#EXTM3U"]

for a in anchors:
    try:
        anchor_id = a.get("anchorId")
        dt = datetime.now()

        title = (a.get("title") or "").strip()
        competition_name = (a.get("competitionName") or "").strip()
        game_type = (a.get("gameType") or "").strip()
        
        team_match = None
        if "vs" in title or "VS" in title or "vs." in title:
            team_match = title
        
        league_name = ""
        if competition_name:
            league_name = competition_name
        elif a.get("mark") and a.get("mark").get("markName"):
            league_name = a.get("mark").get("markName")
        
        extra_info = ""
        if game_type:
            extra_info = game_type
        elif a.get("liveTypeName"):
            extra_info = a.get("liveTypeName")
        
        components = []
        if team_match:
            team_match = team_match.replace("vs", " - ").replace("VS", " - ").replace("vs.", " - ")
            components.append(team_match)
        else:
            components.append(title)
        
        if extra_info:
            if not (extra_info.startswith("[") and extra_info.endswith("]")):
                components.append(f"[{extra_info}]")
            else:
                components.append(extra_info)
        
        if league_name:
            components.append(league_name)
        
        base_title = " ".join(components).strip()
        base_title = re.sub(r'\s+', ' ', base_title)
        base_title = translate_text(base_title, TARGET_LANG)

        time_prefix = dt.strftime('%d/%m-%H.%M')
        final_title = f"{time_prefix} {base_title}"
        final_title = clean_title(final_title)

        lines.append(f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{logo}",{final_title}')
        lines.append(f"#EXTVLCOPT:http-user-agent={UA}")
        lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
        lines.append(f"{WORKER_URL}/?anchorId={anchor_id}")

    except Exception as e:
        print("⚠️ Error build M3U:", e)
        print(f"⚠️ Data yang error: {a}")

with open("CONGOR.m3u", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("✅ File CONGOR.m3u berhasil dibuat")
