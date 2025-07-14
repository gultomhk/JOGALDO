from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {CONFIG_FILE}")

config = load_config(CONFIG_FILE)
BASE_URL = config["BASE_URL"]
USER_AGENT = config["USER_AGENT"]
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": BASE_URL
}

now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========= Ambil daftar slug =========
def extract_slugs_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs = set()
    for row in matches:
        slug = None

        link = row.select_one("a[href^='/match/']")
        if link:
            slug = link['href'].replace('/match/', '').strip()

        if not slug and row.has_attr("onclick"):
            match = re.search(r"/match/([^']+)", row["onclick"])
            if match:
                slug = match.group(1).strip()

        if not slug or slug in slugs:
            continue

        waktu_tag = row.select_one(".match-time")
        if waktu_tag and waktu_tag.get("data-timestamp"):
            timestamp = int(waktu_tag["data-timestamp"])
            event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))

            if event_time_local < (now - timedelta(hours=2)):
                continue

        slugs.add(slug)

    print(f"📦 Total slug valid: {len(slugs)}")
    return list(slugs)

# ========= Ambil link m3u8 dari slug =========
def fetch_map(slugs):
    map_data = {}

    for slug in slugs:
        try:
            print(f"🌐 Proses slug: {slug}")
            url = f"{BASE_URL}/match/{slug}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")
            iframe = soup.select_one("iframe[src*='link=']")

            if not iframe:
                print(f"❌ iframe tidak ditemukan untuk: {slug}")
                continue

            full_url = urljoin(BASE_URL, iframe["src"])
            query = parse_qs(urlparse(full_url).query)
            m3u8_encoded = query.get("link", [""])[0]

            if not m3u8_encoded:
                print(f"⚠️ Tidak ada parameter link= di iframe untuk: {slug}")
                continue

            m3u8_url = unquote(m3u8_encoded)
            if ".m3u8" in m3u8_url:
                map_data[slug] = m3u8_url
                print(f"✅ M3U8 valid: {slug} -> {m3u8_url}")
            else:
                print(f"⚠️ Link tidak valid (bukan .m3u8): {m3u8_url}")

        except Exception as e:
            print(f"❌ Error saat memproses {slug}: {e}")

    return map_data

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)

    # Load map lama jika ada
    out_path = Path("map2.json")
    if out_path.exists():
        old_map = json.loads(out_path.read_text(encoding="utf-8"))
    else:
        old_map = {}

    # Filter slug yang belum ada di map lama
    new_slugs = [slug for slug in slug_list if slug not in old_map]

    if not new_slugs:
        print("🟡 Tidak ada slug baru untuk diproses.")
        exit()

    # Ambil m3u8 hanya untuk slug baru
    new_map = fetch_map(new_slugs)

    # Gabung data lama dan baru
    old_map.update(new_map)
    out_path.write_text(json.dumps(old_map, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ map2.json berhasil diupdate! Total entri: {len(old_map)}")
