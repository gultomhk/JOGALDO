import requests
import urllib.parse
import json
from bs4 import BeautifulSoup
from datetime import datetime
from pytz import timezone
from pathlib import Path
import urllib3
import re

# Matikan peringatan SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Zona waktu WIB
wib = timezone("Asia/Jakarta")

# Load konfigurasi dari file eksternal
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

DOMAIN = CONFIG["DOMAIN"]
PROXY_LIST_URL = CONFIG["PROXY_LIST_URL"]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}

# =========================
# Class
# =========================
class JetLink:
    def __init__(self, url, name=None, headers=None):
        self.url = url
        self.name = name or url
        self.headers = headers or {}

class JetItem:
    def __init__(self, title, links, league, starttime, page_url=None):
        self.title = title
        self.links = links
        self.league = league
        self.starttime = starttime
        self.page_url = page_url

# =========================
# Fungsi proxy
# =========================
def load_proxies():
    try:
        print("🌐 Mengambil daftar proxy...")
        resp = requests.get(PROXY_LIST_URL, timeout=10)
        resp.raise_for_status()
        return [p.strip() for p in resp.text.splitlines() if p.strip()]
    except Exception as e:
        print(f"⚠️ Gagal ambil proxy: {e}")
        return []

def safe_get(url, proxies):
    for p in proxies:
        proxy = {"http": p, "https": p}
        try:
            r = requests.get(url, headers=HEADERS, timeout=10, proxies=proxy, verify=False)
            if r.status_code == 200:
                print(f"↪️ OK: {url} via {p}")
                return r.text
        except:
            continue
    print(f"❌ Gagal ambil {url} dengan semua proxy.")
    return None

# =========================
# Fungsi parsing HTML
# =========================
def parse_html(html, selector, item_parser):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for m in soup.select(selector):
        try:
            ts = int(m.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            items.append(item_parser(m, dt))
        except Exception as e:
            print("⚠️ Parse error:", e)
            continue
    return items

def parse_item(m, dt):
    t1 = m.select_one("span.name-team-left").text.strip()
    t2 = m.select_one("span.name-team-right").text.strip()
    title = f"{t1} vs {t2}"

    league = (
        m.select_one("p.tour-name").text.strip()
        if m.select_one("p.tour-name")
        else m.select_one("div.tournament").text.strip()
    )

    href = m.select_one("a.btn-watch") or m.select_one("a")
    full_url = href.get("href")
    full_url = full_url if full_url.startswith("http") else f"https://{DOMAIN}{full_url}"

    # ✅ Cari langsung .m3u8 di blok ini
    raw_html = str(m)
    m3u8_matches = re.findall(r'https.*?\.m3u8[^"\'<> ]*', raw_html)

    links = []
    for link in set(m3u8_matches):
        if any(x in link for x in ["jwplatform", "cloudflare", "akamaihd"]):
            continue
        links.append(JetLink(link))

    return JetItem(title, links, league, dt, page_url=full_url)

# =========================
# Simpan ke JSON
# =========================
def save_to_map3_json(items, file="map3.json"):
    result = {}
    for item in items:
        page_url = item.page_url
        if not page_url:
            continue
        path = urllib.parse.urlparse(page_url).path.strip("/")
        if path.endswith(".html"):
            slug = path.split("/")[-1].removesuffix(".html")
        else:
            continue
        for link in item.links:
            result[slug] = link.url
    Path(file).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"✅ JSON disimpan: {file}")

# =========================
# Main
# =========================
def main():
    proxies = load_proxies()
    if not proxies:
        return

    # ✅ Hanya scrape dari playing.html
    playing_html = safe_get(f"https://{DOMAIN}/playing.html", proxies)
    playing = parse_html(playing_html, "div.row-item-match", parse_item) if playing_html else []

    print(f"\n📡 Total Live Match: {len(playing)}")
    for item in playing:
        print(f"🕒 {item.starttime.strftime('%d/%m %H:%M')} | {item.league} | {item.title}")
        for l in item.links:
            print("   🎯", l.url)

    save_to_map3_json(playing)

if __name__ == "__main__":
    main()
