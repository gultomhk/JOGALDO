from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import tz
from pathlib import Path
import requests
import re

# ====== Konfigurasi ======
BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not BODATTVDATA_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {BODATTVDATA_FILE}")

config = load_config(BODATTVDATA_FILE)
required_keys = ["DEFAULT_URL", "BASE_URL", "WORKER_URL", "LOGO", "USER_AGENT"]
missing = [key for key in required_keys if key not in config]
if missing:
    raise ValueError(f"❌ Missing config keys: {', '.join(missing)}")

BASE_URL = config["BASE_URL"]
WORKER_URL = config["WORKER_URL"]
LOGO = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    matches = soup.select("div.common-table-row.table-row, div.slide-item")
    print(f"⛵️ Found {len(matches)} match items")

    for item in matches:
        try:
            # --- slug / link ---
            link_tag = item.select_one("a[href^='/match/']")
            if not link_tag:
                continue
            slug = link_tag['href'].replace('/match/', '').strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)

            # --- waktu ---
            ts_tag = item.select_one(".match-time[data-timestamp]")
            if ts_tag and ts_tag.get("data-timestamp"):
                try:
                    timestamp = int(ts_tag["data-timestamp"])
                    event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                    waktu = event_time_local.strftime("%d/%m-%H.%M")
                except Exception as e:
                    print(f"⚠️ Gagal parsing timestamp: {e}")
                    waktu = "00/00-00.00"
            else:
                waktu = "00/00-00.00"

            # --- nama liga ---
            # Ambil dari URL slug terakhir (biasanya mengandung nama olahraga/league)
            # contoh slug: los-angeles-dodgers-vs-philadelphia-phillies-baseball-177734
            league_match = re.search(r"-([a-z]+)-\d+$", slug)
            league = league_match.group(1).upper() if league_match else "Unknown League"
            if league == "BASEBALL":
                league = "MLB"

            # --- nama tim ---
            clubs = [c.get_text(strip=True) for c in item.select(".club-name")]
            if len(clubs) >= 2:
                title = f"{clubs[0]} vs {clubs[1]}"
            else:
                title = clean_title(slug.replace("-", " "))

            if not title or len(title) < 3:
                continue

            print(f"📃 Parsed: {waktu} | {league} | {title}")

            # --- buat entri M3U ---
            full_title = f"{title} - {league}"
            output += [
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {full_title}',
                f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                f'{WORKER_URL}{slug}'
            ]

        except Exception as e:
            print(f"❌ Error parsing match: {e}")
            continue

    return "\n".join(output)

# =====================
# MAIN
# =====================
if __name__ == "__main__":
    with open("BODATTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = extract_matches_from_html(html)

    with open("bodattv_live.m3u", "w", encoding="utf-8") as f:
        f.write(result)

    print("\n✅ File bodattv_live.m3u berhasil dibuat tanpa ekstraksi .m3u8")
