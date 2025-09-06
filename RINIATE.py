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

# Load konfigurasi
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
    def __init__(self, url, name=None):
        self.url = url
        self.name = name or url

class JetItem:
    def __init__(self, title, links, league, starttime, page_url=None):
        self.title = title
        self.links = links
        self.league = league
        self.starttime = starttime
        self.page_url = page_url

# =========================
# Proxy
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

def safe_get(url, proxies, timeout=10):
    for p in proxies:
        proxy = {"http": p, "https": p}
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, proxies=proxy, verify=False)
            if r.status_code == 200:
                print(f"↪️ OK: {url} via {p}")
                return r.text
        except Exception:
            continue
    print(f"❌ Gagal ambil {url} dengan semua proxy.")
    return None

# =========================
# Ambil link .m3u8
# =========================
def get_links(live_url, proxies):
    html = safe_get(live_url, proxies)
    if not html:
        return []

    links = []
    soup = BeautifulSoup(html, "html.parser")

    # Cari <a data-url>
    for a in soup.select("div.info-section a[data-url]"):
        url = a.get("data-url")
        if url and url.endswith(".m3u8") and url not in [l.url for l in links]:
            links.append(JetLink(url))

    # fallback: regex di HTML
    if not links:
        print(f"⚠️ Tidak ditemukan <a data-url> di {live_url}, fallback regex")
        for link in set(re.findall(r'https.*?\.m3u8[^"\'<> ]*', html)):
            if link not in [l.url for l in links]:
                links.append(JetLink(link))

    return links

# =========================
# Parsing HTML
# =========================
def parse_item(m, dt, proxies):
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

    links = get_links(full_url, proxies)
    return JetItem(title, links, league, dt, page_url=full_url)

def parse_html(html, selector, item_parser, proxies):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for m in soup.select(selector):
        try:
            ts = int(m.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            items.append(item_parser(m, dt, proxies))
        except Exception as e:
            print("⚠️ Parse error:", e)
            continue
    return items

# =========================
# Simpan JSON
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
        # simpan semua link .m3u8, bisa array
        result[slug] = [l.url for l in item.links]
    Path(file).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"✅ JSON disimpan: {file}")

# =========================
# Main
# =========================
def main():
    proxies = load_proxies()
    if not proxies:
        return

    playing_html = safe_get(f"https://{DOMAIN}/playing.html", proxies)
    playing = parse_html(playing_html, "div.row-item-match", parse_item, proxies) if playing_html else []

    print(f"\n📡 Total Live Match: {len(playing)}")
    for item in playing:
        print(f"🕒 {item.starttime.strftime('%d/%m %H:%M')} | {item.league} | {item.title}")
        for l in item.links:
            print("   🎯", l.url)

    save_to_map3_json(playing)

if __name__ == "__main__":
    main()
