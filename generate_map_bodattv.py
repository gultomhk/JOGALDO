import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import tz
from pathlib import Path
import json
import re
import urllib.parse

CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

# ==== Load Config ====
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

# ==== Ekstrak slug ====
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    return None

# ==== Ambil URL m3u8 ====
def extract_m3u8_urls(html):
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for i, tag in enumerate(data_links):
        raw = tag.get("data-link", "")
        if raw.endswith(".m3u8") and raw.startswith("http"):
            print(f"   🔗 Cek iframe dari data-link: {raw}")
            m3u8_urls.append(raw)
        elif "/player?link=" in raw:
            decoded = urllib.parse.unquote(raw)
            if decoded.endswith(".m3u8") and decoded.startswith("http"):
                print(f"   🔗 Langsung dari iframe: {raw} → ✅ {decoded}")
                m3u8_urls.append(decoded)
            else:
                print(f"   ⚠️ Skip iframe (bukan m3u8): {raw}")
    return m3u8_urls

# ==== Simpan ke file ====
def save_to_map(result_dict):
    MAP_FILE.write_text(json.dumps(result_dict, indent=2))
    print(f"💾 Total tersimpan: {len(result_dict)} ke {MAP_FILE}")

# ==== Main logic ====
def main():
    response = requests.get(BASE_URL, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(rows)}")

    result = {}
    for row in rows:
        slug = extract_slug(row)
        if not slug:
            continue

        print(f"\n🔍 Scraping slug: {slug}")
        match_url = f"{BASE_URL}/match/{slug}"
        try:
            r = requests.get(match_url, headers=HEADERS, timeout=10)
            urls = extract_m3u8_urls(r.text)

            if urls:
                if len(urls) == 1:
                    result[slug] = urls[0]
                else:
                    for i, u in enumerate(urls, start=1):
                        result[f"{slug} server{i}"] = u
            else:
                print(f"⚠️ Tidak ada .m3u8 ditemukan di {slug}")

        except Exception as e:
            print(f"❌ Gagal ambil {slug}: {e}")

    save_to_map(result)

if __name__ == "__main__":
    main()
