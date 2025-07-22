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
MAP_FILE = Path("map2.json")

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

    slugs = []
    seen = set()
    for row in matches:
        slug = None
        link = row.select_one("a[href^='/match/']")
        if link:
            slug = link['href'].replace('/match/', '').strip()
        elif row.has_attr("onclick"):
            match = re.search(r"/match/([^']+)", row["onclick"])
            if match:
                slug = match.group(1).strip()

        if not slug or slug in seen:
            continue

        waktu_tag = row.select_one(".match-time")
        if waktu_tag and waktu_tag.get("data-timestamp"):
            timestamp = int(waktu_tag["data-timestamp"])
            event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            if event_time_local < (now - timedelta(hours=2)):
                continue

        seen.add(slug)
        slugs.append(slug)

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Simpan ke MAP (gaya save_to_map) =========
def save_to_map(slugs):
    old_data = {}
    if MAP_FILE.exists():
        with MAP_FILE.open(encoding="utf-8") as f:
            old_data = json.load(f)

    new_data = {}
    total = len(slugs)

    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{total}] ▶ Scraping slug: {slug}", flush=True)
        try:
            url = f"{BASE_URL}/match/{slug}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            iframe = soup.select_one("iframe[src*='link=']")
            if not iframe:
                print(f"   ❌ iframe tidak ditemukan untuk: {slug}", flush=True)
                continue

            full_url = urljoin(BASE_URL, iframe["src"])
            m3u8_encoded = parse_qs(urlparse(full_url).query).get("link", [""])[0]
            m3u8_url = unquote(m3u8_encoded)

            if ".m3u8" in m3u8_url:
                new_data[slug] = m3u8_url
                print(f"   ✅ M3U8 valid: {m3u8_url}", flush=True)
            else:
                print(f"   ⚠️ Link bukan .m3u8: {m3u8_url}", flush=True)

        except Exception as e:
            print(f"   ❌ Error slug {slug}: {e}", flush=True)

    # Gabungkan, urutkan berdasarkan slugs (yang diprioritaskan), dan simpan hanya 100 entri terakhir
    combined = {**old_data, **new_data}
    ordered = dict(sorted(combined.items(), key=lambda x: slugs.index(x[0]) if x[0] in slugs else 9999))

    # Potong ke 100 entri terakhir
    limited = dict(list(ordered.items())[-100:])

    if not MAP_FILE.exists() or limited != old_data:
        with MAP_FILE.open("w", encoding="utf-8") as f:
            json.dump(limited, f, indent=2, ensure_ascii=False)
        print(f"✅ map2.json berhasil diupdate! Total entri: {len(limited)}")
    else:
        print("ℹ️ Tidak ada perubahan. map2.json tidak ditulis ulang.")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    save_to_map(slug_list)
