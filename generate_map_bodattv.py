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

# ========= Ambil daftar slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    
    return None

def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs, seen = [], set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))

                if event_time_local < (now - timedelta(hours=hours_threshold)):
                    continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Ekstraksi m3u8 =========
def extract_m3u8_links_from_url(url):
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []

        return re.findall(r"https?://[^\s\"']+\.m3u8", resp.text)
    except Exception as e:
        print(f"   ⚠️ Gagal ambil iframe {url}: {e}")
        return []

def get_all_m3u8_from_page(soup, slug):
    all_m3u8 = []

    # Cek tombol server dengan data-link
    server_buttons = soup.select("button[data-link], a[data-link]")
    for btn in server_buttons:
        iframe_rel_url = btn.get("data-link")
        if not iframe_rel_url:
            continue
        iframe_url = urljoin(BASE_URL, iframe_rel_url)
        print(f"   🔗 Cek iframe dari data-link: {iframe_url}")
        all_m3u8 += extract_m3u8_links_from_url(iframe_url)

    # Cek iframe langsung (jika ada iframe[src] yang sudah .m3u8)
    iframe_tags = soup.select("iframe[src*='.m3u8']")
    for iframe in iframe_tags:
        iframe_src = urljoin(BASE_URL, iframe.get("src"))
        print(f"   🔗 Cek iframe langsung: {iframe_src}")
        all_m3u8.append(iframe_src)

    return list(set(all_m3u8))

# ========= Simpan ke MAP =========
def save_to_map(slugs):
    old_data = {}
    if MAP_FILE.exists():
        with MAP_FILE.open(encoding="utf-8") as f:
            old_data = json.load(f)

    new_data = {}
    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{len(slugs)}] ▶ Scraping slug: {slug}", flush=True)
        try:
            r = requests.get(f"{BASE_URL}/match/{slug}", headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            m3u8_list = get_all_m3u8_from_page(soup, slug)

            if m3u8_list:
                new_data[slug] = m3u8_list
                print(f"   ✅ {len(m3u8_list)} M3U8 ditemukan.", flush=True)
            else:
                print(f"   ⚠️ Tidak ada .m3u8 ditemukan di {slug}", flush=True)

        except Exception as e:
            print(f"   ❌ Error slug {slug}: {e}", flush=True)

    combined = {**old_data, **new_data}
    ordered = {k: combined[k] for k in slugs if k in combined}
    limited = dict(list(ordered.items())[-100:])

    if not MAP_FILE.exists() or json.dumps(limited, sort_keys=True) != json.dumps(old_data, sort_keys=True):
        with MAP_FILE.open("w", encoding="utf-8") as f:
            json.dump(limited, f, indent=2, ensure_ascii=False)
        print(f"✅ map2.json berhasil disimpan! Total entri: {len(limited)}")
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
