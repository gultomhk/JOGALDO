from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin
import urllib.parse

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

# ========= Fungsi Ekstraksi M3U8 =========
def extract_m3u8_urls(html):
    """Ekstrak URL m3u8 dari HTML dengan berbagai metode"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if raw.endswith(".m3u8") and raw.startswith("http"):
            print(f"   🔗 Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)
        elif "/player?link=" in raw:
            decoded = urllib.parse.unquote(raw)
            if decoded.endswith(".m3u8") and decoded.startswith("http"):
                print(f"   🔗 Dari iframe: ✅ {decoded}")
                m3u8_urls.append(decoded)
            else:
                print(f"   ⚠️ Iframe tapi bukan m3u8: {raw}")
        else:
            print(f"   ⚠️ Skip: {raw}")
    return m3u8_urls

# ========= Ambil daftar slug =========
def extract_slug(row):
    """Ekstrak slug dari elemen baris HTML."""
    # Coba dari atribut onclick dulu
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    
    # Fallback ke <a href="/match/...">
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    
    return None

def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            # Ambil timestamp dan filter jika lebih dari threshold jam yang lalu
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

# ========= Simpan ke MAP =========
def save_to_map(slugs):
    """Simpan URL m3u8 ke file map dengan berbagai metode ekstraksi"""
    # Load data lama jika ada
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
            
            # Coba ekstrak dengan berbagai metode
            m3u8_urls = extract_m3u8_urls(r.text)
            
            if not m3u8_urls:
                # Fallback ke metode iframe lama
                soup = BeautifulSoup(r.text, "html.parser")
                iframe = soup.select_one("iframe[src*='link=']")
                if iframe:
                    m3u8_encoded = parse_qs(urlparse(urljoin(BASE_URL, iframe["src"])).query).get("link", [""])[0]
                    m3u8_url = unquote(m3u8_encoded)
                    if ".m3u8" in m3u8_url:
                        m3u8_urls.append(m3u8_url)
            
            # Simpan semua URL yang ditemukan
            for i, url in enumerate(m3u8_urls, 1):
                key = f"{slug} server{i}" if len(m3u8_urls) > 1 else slug
                new_data[key] = url
                print(f"   ✅ M3U8 ditemukan ({i}): {url}", flush=True)
                
        except Exception as e:
            print(f"   ❌ Error slug {slug}: {e}", flush=True)

    # Gabungkan data lama dan baru
    combined = {**old_data, **new_data}

    # Filter hanya slug yang diminta
    ordered = {k: combined[k] for k in slugs if k in combined}
    limited = dict(list(ordered.items())[-100:])  # Batas maksimal 100 entri

    # Hanya simpan jika ada perubahan data atau file belum ada
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
