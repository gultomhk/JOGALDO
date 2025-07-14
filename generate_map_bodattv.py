from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin

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
BASE_URL = config["BASE_URL"]
USER_AGENT = config["USER_AGENT"]

now = datetime.now(tz.gettz("Asia/Jakarta"))

# ====== Ambil daftar slug dari HTML ======
def extract_slug_list(html):
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    slugs = []

    matches_table = soup.select("div.common-table-row.table-row")

    for row in matches_table:
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
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            is_exception = any(k in slug.lower() for k in ["tennis", "billiards", "snooker", "worldssp", "superbike"])
            if not is_exception and event_time_local < (now - timedelta(hours=2)):
                continue

            slugs.append(slug)

        except Exception:
            continue

    return slugs

# ====== Ambil m3u8 URL berdasarkan slug ======
def fetch_map(slugs):
    map_data = {}

    for slug in slugs:
        try:
            url = f"{BASE_URL}/match/{slug}"
            r = requests.get(url, headers={
                "User-Agent": USER_AGENT,
                "Referer": BASE_URL
            }, timeout=10)

            tree = BeautifulSoup(r.text, "html.parser")
            iframe = tree.select_one("iframe[src*='link=']")
            if not iframe:
                continue

            src = iframe["src"]
            full_url = urljoin(BASE_URL, src)
            link_encoded = parse_qs(urlparse(full_url).query).get("link", [""])[0]
            final_url = unquote(link_encoded)

            if final_url.endswith(".m3u8"):
                map_data[slug] = final_url
                print(f"✅ {slug} → {final_url}")

        except Exception as e:
            print(f"❌ Error slug {slug}: {e}")
            continue

    return map_data

# ====== Main Execution ======
html_file = Path("BODATTV_PAGE_SOURCE.html")
if not html_file.exists():
    raise FileNotFoundError("❌ File HTML tidak ditemukan")

html = html_file.read_text(encoding="utf-8")
slug_list = extract_slug_list(html)
print(f"📦 Total slug valid: {len(slug_list)}")

map_result = fetch_map(slug_list)
Path("map.json").write_text(json.dumps(map_result, indent=2, ensure_ascii=False), encoding="utf-8")
print("✅ map.json berhasil dibuat!")
