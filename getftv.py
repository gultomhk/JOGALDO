import json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re

# ========== CONFIG ==========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")  # tempat penyimpanan slug -> m3u8

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"❌ Config file tidak ditemukan: {CONFIG_FILE}")
config = load_config(CONFIG_FILE)

BASE_URL = config["BASE_URL"]
WORKER_URL = config["WORKER_URL"]
LOGO = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========== HELPERS ==========
def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def load_map():
    if MAP_FILE.exists():
        with open(MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# ========== PARSING ==========
def extract_matches_from_html(html, slug_to_url_map):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    matches = soup.select("div.common-table-row.table-row")
    print(f"⛵️ Found {len(matches)} match rows")

    for row in matches:
        try:
            slug = None

            link = row.select_one("a[href^='/match/']")
            if link:
                slug = link['href'].replace('/match/', '').strip()

            if not slug and row.has_attr("onclick"):
                match = re.search(r"/match/([^']+)", row["onclick"])
                if match:
                    slug = match.group(1).strip()

            if not slug or slug in seen:
                continue
            seen.add(slug)

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                local_time = utc_time.astimezone(tz.gettz("Asia/Jakarta"))
                waktu = local_time.strftime("%d/%m-%H.%M")
            else:
                waktu = "00/00-00.00"
                local_time = now

            # pengecualian
            slug_lower = slug.lower()
            is_exception = any(word in slug_lower for word in ["tennis", "snooker", "superbike", "billiards", "worldssp"])
            if not is_exception and local_time < (now - timedelta(hours=2)):
                continue

            wrapper = row.select_one(".list-club-wrapper")
            if wrapper:
                names = wrapper.select(".club-name")
                texts = [t.text.strip() for t in names if t.text.strip().lower() != "vs"]
                if len(texts) >= 2:
                    title = f"{texts[0]} vs {texts[1]}"
                elif len(texts) == 1:
                    title = texts[0]
                else:
                    title = wrapper.get_text(separator=" ", strip=True)
            else:
                title = slug.replace("-", " ")

            title = clean_title(title)
            if title.lower() == "vs" or len(title) < 3:
                continue

            urls = slug_to_url_map.get(slug)
            if not urls:
                # fallback slug langsung tanpa server
                urls = [f"{WORKER_URL}{slug}"]
            elif isinstance(urls, str):
                urls = [urls]

            for i, url in enumerate(urls):
                server_label = f" server {i+1}" if len(urls) > 1 else ""
                output += [
                    f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {title}{server_label}',
                    f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                    f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                    url
                ]

        except Exception as e:
            print(f"❌ Error row: {e}")
            continue

    return "\n".join(output)

# ========== MAIN ==========
if __name__ == "__main__":
    with open("BODATTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()

    slug_to_url_map = load_map()
    result = extract_matches_from_html(html, slug_to_url_map)

    with open("bodattv_live.m3u", "w", encoding="utf-8") as f:
        f.write(result)

    print("\n✅ File bodattv_live.m3u berhasil dibuat.")
