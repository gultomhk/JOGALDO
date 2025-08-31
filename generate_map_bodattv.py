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
    """Ekstrak URL m3u8 dari HTML dengan query string penuh"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if ".m3u8" in raw and raw.startswith("http"):
            # simpan URL utuh (termasuk ?auth_key=...)
            print(f"   🔗 Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)
        elif "/player?link=" in raw:
            decoded = urllib.parse.unquote(raw)
            if ".m3u8" in decoded and decoded.startswith("http"):
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

            # ⏰ Ambil timestamp pertandingan
            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                waktu = event_time_local.strftime("%d/%m-%H.%M")
            else:
                waktu = "00/00-00.00"
                event_time_local = now

            # 🔴 Cek apakah sedang live
            is_live = row.select_one(".live-text") is not None

            # ⏩ Skip jika lewat waktu threshold & bukan live
            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

            # 🚫 Skip keyword pengecualian
            slug_lower = slug.lower()
            is_exception = any(
                keyword in slug_lower
                for keyword in ["tennis", "billiards", "snooker", "worldssp", "superbike"]
            )
            if not is_live and not is_exception and event_time_local < (now - timedelta(hours=hours_threshold)):
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
    new_data = {}

    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{len(slugs)}] ▶ Scraping slug: {slug}", flush=True)

        try:
            r = requests.get(f"{BASE_URL}/match/{slug}", headers=HEADERS, timeout=15)
            r.raise_for_status()

            # Ekstrak m3u8 dari halaman HTML
            m3u8_urls = extract_m3u8_urls(r.text)

            # Fallback ke iframe player jika belum ketemu
            if not m3u8_urls:
                soup = BeautifulSoup(r.text, "html.parser")
                iframe = soup.select_one("iframe[src*='link=']")
                if iframe:
                    iframe_url = urljoin(BASE_URL, iframe["src"])
                    decoded = unquote(iframe_url)
                    if ".m3u8" in decoded:
                        m3u8_urls.append(decoded)

            # Simpan hasil
            if m3u8_urls:
                if len(m3u8_urls) == 1:
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 ditemukan: {m3u8_urls[0]}", flush=True)
                else:
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 ditemukan (server1): {m3u8_urls[0]}", flush=True)

                    for i, url in enumerate(m3u8_urls[1:], start=2):
                        key = f"{slug}server{i}"
                        new_data[key] = url
                        print(f"   ✅ M3U8 ditemukan (server{i}): {url}", flush=True)
            else:
                print(f"   ⚠️ Tidak ditemukan .m3u8 pada slug: {slug}", flush=True)

        except Exception as e:
            print(f"   ❌ Error saat proses slug '{slug}': {e}", flush=True)

    # Simpan hanya data baru yang berhasil
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)

    print(f"✅ map2.json berhasil disimpan! Total entri berhasil: {len(new_data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    save_to_map(slug_list)
