import asyncio
import json
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from pathlib import Path

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

# ========= Load Config =========
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
BASE_URL = config.get("BASE_URL", "https://fstv.space")
USER_AGENT = config.get("USER_AGENT")
HEADLESS = config.get("HEADLESS", "true").lower() != "false"

# Output file
OUTPUT_FILE = MAP_FILE

# ==========================
# Ambil HTML langsung
# ==========================
def fetch_html(url):
    scraper = cloudscraper.create_scraper()
    headers = {"User-Agent": USER_AGENT} if USER_AGENT else {}
    r = scraper.get(url, headers=headers, timeout=20)
    if r.status_code == 200 and "<html" in r.text.lower():
        print("✅ Berhasil ambil HTML")
        return r.text
    raise RuntimeError(f"❌ Gagal ambil HTML: status_code={r.status_code}")

# ==========================
# Ekstrak M3U8
# ==========================
def extract_m3u8_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.find("iframe", src=True)
    if not iframe:
        print("❌ Tidak ada iframe ditemukan.")
        return []

    src = iframe["src"]
    iframe_url = urljoin(base_url, src)
    print(f"🔗 iframe src: {iframe_url}")

    if "link=" in iframe_url:
        part = iframe_url.split("link=", 1)[1].split("&", 1)[0]
        m3u8_url = unquote(part)
        print(f"✅ Ditemukan link M3U8: {m3u8_url}")
        return [m3u8_url]
    else:
        print("❌ Tidak ada parameter link= pada iframe.")
        return []

# ==========================
# Ekstrak slug
# ==========================
def extract_slug(row):
    if row.has_attr("onclick"):
        import re
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link["href"].replace("/match/", "").strip()
    return None

def extract_slugs_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    return [extract_slug(row) for row in matches if extract_slug(row)]

# ==========================
# Main logic
# ==========================
async def main():
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")

    # halaman tunggal
    if "iframe" in html and "btn-server" in html:
        print("📺 Mode: halaman pertandingan tunggal")
        m3u8_links = extract_m3u8_from_html(html, BASE_URL)
        data = {"single_match": m3u8_links[0] if m3u8_links else None}
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Disimpan ke {OUTPUT_FILE}")

    # halaman daftar
    else:
        print("📋 Mode: halaman daftar pertandingan")
        slugs = extract_slugs_from_html(html)
        print(f"🔍 Total slug ditemukan: {len(slugs)}")
        map_data = {}

        for slug in slugs:
            url = f"{BASE_URL}/match/{slug}"
            try:
                page_html = fetch_html(url)
                m3u8_links = extract_m3u8_from_html(page_html, url)
                if m3u8_links:
                    map_data[slug] = m3u8_links[0]  # ambil yang pertama saja
            except Exception as e:
                print(f"⚠️ Gagal proses slug {slug}: {e}")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(map_data, f, indent=2, ensure_ascii=False)
        print(f"💾 Disimpan ke {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
