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
LOGO_DEFAULT = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

def clean_title(title):
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()
    current_group_label = ""

    # Loop per section tanggal
    for section in soup.select("div.league-info-wrapper.group-by-datetime"):
        group_label = section.select_one(".league-name")
        if group_label:
            current_group_label = group_label.get_text(strip=True)

        # Ambil semua pertandingan setelah wrapper ini sampai wrapper berikutnya
        next_siblings = section.find_all_next("div", class_="common-table-row")
        for item in next_siblings:
            # Jika menemukan wrapper group-by-datetime baru → stop loop untuk group ini
            if "group-by-datetime" in item.get("class", []):
                break

            try:
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
                        waktu = "00/00-00.00"
                else:
                    waktu = "00/00-00.00"

                # --- nama liga ---
                league_tag = item.select_one("a.league-name")
                league = league_tag.get_text(strip=True) if league_tag else "Unknown League"

                # --- logo liga ---
                logo_tag = item.select_one(".logo-league")
                if logo_tag and "background-image" in logo_tag.get("style", ""):
                    m = re.search(r"url\(['\"]?(.*?)['\"]?\)", logo_tag["style"])
                    league_logo = m.group(1) if m else LOGO_DEFAULT
                else:
                    league_logo = LOGO_DEFAULT

                # --- nama tim ---
                clubs = [c.get_text(strip=True) for c in item.select(".club-name")]
                if len(clubs) >= 2:
                    title = f"{clubs[0]} vs {clubs[1]}"
                else:
                    title = clean_title(slug.replace("-", " "))

                if not title or len(title) < 3:
                    continue

                # --- gabungkan semua info ---
                full_title = f"{title} - {league}"
                group_label_text = f"{current_group_label or 'Today'}"

                print(f"📃 {group_label_text} | {waktu} | {league} | {title}")

                # --- entri M3U ---
                output += [
                    f'#EXTINF:-1 group-title="⚽️| {group_label_text}" tvg-logo="{league_logo}",{waktu} {full_title}',
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

    print("\n✅ File bodattv_live.m3u berhasil dibuat lengkap (liga, logo, group, slug)")
