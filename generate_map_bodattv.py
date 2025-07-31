import re
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime
from dateutil import tz

# === Konfigurasi dan global ===
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

# === Ekstraksi slug dari HTML ===
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()

    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    return None

# === Ambil HTML halaman utama dan slug pertandingan ===
def fetch_match_slugs():
    resp = requests.get(BASE_URL, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("div.common-table-row.table-row")
    print(f"📦 Total pertandingan ditemukan: {len(rows)}")
    
    slugs = []
    seen = set()
    for row in rows:
        slug = extract_slug(row)
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs

# === Ambil semua URL .m3u8 dari satu halaman pertandingan ===
def extract_m3u8_links_from_url(iframe_url):
    try:
        resp = requests.get(iframe_url, headers=HEADERS, timeout=10)
        matches = re.findall(r'(https?://[^\s\'"]+\.m3u8)', resp.text)
        return list(set(matches))
    except Exception as e:
        print(f"   ⚠️ Gagal ambil iframe: {e}")
        return []

def get_all_m3u8_from_page(soup, slug):
    found_links = set()

    # Dari tombol dengan data-link langsung .m3u8
    for btn in soup.select("button[data-link], a[data-link]"):
        data_link = btn.get("data-link")
        if not data_link:
            continue

        if ".m3u8" in data_link:
            print(f"   🔗 Langsung .m3u8 dari tombol: {data_link}")
            found_links.add(data_link)
        else:
            iframe_url = urljoin(BASE_URL, data_link)
            print(f"   🔍 Periksa isi iframe: {iframe_url}")
            m3u8s = extract_m3u8_links_from_url(iframe_url)
            for url in m3u8s:
                found_links.add(url)

    # Dari iframe dengan src langsung ke .m3u8
    for iframe in soup.select("iframe[src*='.m3u8']"):
        src = iframe.get("src")
        if src:
            print(f"   🔗 Langsung dari iframe: {src}")
            found_links.add(src)

    return list(found_links)

# === Simpan hasil ke map2.json ===
def save_to_map(data_dict):
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data_dict, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Disimpan ke {MAP_FILE} ({len(data_dict)} entri)")

# === Main ===
def main():
    slugs = fetch_match_slugs()
    result = {}

    for slug in slugs:
        print(f"\n🔍 Proses slug: {slug}")
        full_url = urljoin(BASE_URL, f"/match/{slug}")
        try:
            resp = requests.get(full_url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            m3u8_links = get_all_m3u8_from_page(soup, slug)

            if not m3u8_links:
                print(f"   ⚠️ Tidak ada .m3u8 ditemukan untuk {slug}")
                continue

            if len(m3u8_links) == 1:
                result[slug] = m3u8_links[0]
            else:
                for i, link in enumerate(m3u8_links, 1):
                    result[f"{slug} server{i}"] = link

        except Exception as e:
            print(f"   ❌ Gagal ambil slug {slug}: {e}")

    save_to_map(result)

if __name__ == "__main__":
    main()
