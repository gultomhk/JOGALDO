from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path

# Load config from file
FSTVDATA_FILE = Path.home() / "fstvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not FSTVDATA_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {FSTVDATA_FILE}")

config = load_config(FSTVDATA_FILE)
required_keys = ["DEFAULT_URL", "BASE_URL", "WORKER_URL", "LOGO", "USER_AGENT"]
missing = [key for key in required_keys if key not in config]
if missing:
    raise ValueError(f"❌ Missing config keys: {', '.join(missing)}")

BASE_URL = config["BASE_URL"]
WORKER_URL = config["WORKER_URL"]
LOGO = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

now = datetime.now(tz.gettz("Asia/Jakarta"))

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    # 1. slide-item (Football, MMA, etc.)
    matches_slide = soup.select("div.slide-item")
    print(f"⛓️ Found {len(matches_slide)} slide-item matches")

    for match in matches_slide:
        a_tag = match.select_one('a.btn-club[href]')
        if not a_tag:
            continue

        slug = a_tag['href'].replace('/match/', '').strip()
        if slug in seen:
            continue
        seen.add(slug)

        ts_tag = match.select_one('.timestamp')
        ts_value = ts_tag.get('data-timestamp') if ts_tag else None

        if ts_value:
            timestamp = int(ts_value)
            event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            if event_time_local < (now - timedelta(hours=2)):
                continue
            waktu = event_time_local.strftime("%d/%m-%H.%M")
        else:
            waktu = "00/00-00.00"

        teams = match.select('.club-name')
        team1 = teams[0].text.strip() if len(teams) >= 1 else ""
        team2 = teams[1].text.strip() if len(teams) >= 2 else ""

        if team1:
            title = f"{team1} vs {team2}" if team2 else team1
        else:
            title_raw = slug.replace("-", " ")
            title = title_raw.replace("football", "").strip(" -")

        print(f"📃 Parsed: {waktu} | {title}")

        output += [
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {title}',
            f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
            f'#EXTVLCOPT:http-referrer={BASE_URL}/',
            f'{WORKER_URL}{slug}'
        ]

    # 2. common-table-row (F1, MotoGP, PPV, etc.)
    matches_table = soup.select("div.common-table-row.table-row")
    print(f"⛵️ Found {len(matches_table)} table-row matches")

    for row in matches_table:
        try:
            link = row.select_one("a[href^='/match/']")
            if not link:
                continue
            slug = link['href'].replace('/match/', '').strip()
            if slug in seen:
                continue
            seen.add(slug)

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                if event_time_local < (now - timedelta(hours=2)):
                    continue
                waktu = event_time_local.strftime("%d/%m-%H.%M")
            else:
                waktu = "00/00-00.00"

            # ambil kedua tim dari struktur baru jika ada
            team_tags = row.select(".list-club-wrapper .club-name.text-overflow")
            if len(team_tags) >= 2:
                team1 = team_tags[0].text.strip()
                team2 = team_tags[1].text.strip()
                title = f"{team1} vs {team2}"
            else:
                title_tag = row.select_one(".list-club-wrapper span")
                title = title_tag.text.strip() if title_tag else slug.replace("-", " ").replace("football", "").strip(" -")

            print(f"📃 Parsed: {waktu} | {title}")

            output += [
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {title}',
                f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                f'{WORKER_URL}{slug}'
            ]
        except Exception as e:
            print(f"❌ Error parsing table row: {e}")
            continue

    return "\n".join(output)

if __name__ == "__main__":
    with open("FSTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()
    result = extract_matches_from_html(html)
    with open("fstv_live.m3u", "w", encoding="utf-8") as f:
        f.write(result)
    print("\n✅ File fstv_live.m3u berhasil dibuat dengan filter waktu (2 jam ke depan atau lebih)")
