import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
import json
import urllib.parse
from pytz import timezone
from pathlib import Path
from functools import lru_cache

# Zona waktu lokal
wib = timezone("Asia/Jakarta")

# Konfigurasi Dinamis dari File
AEBABAMI_FILE = Path.home() / "aebabami_file.txt"
CONFIG = {}

with open(AEBABAMI_FILE, "r", encoding="utf-8") as f:
    exec(f.read(), CONFIG)

DOMAIN = CONFIG.get("DOMAIN")
M3U8_TEMPLATE_URL = CONFIG.get("M3U8_TEMPLATE_URL")
WORKER_URL_TEMPLATE = CONFIG.get("WORKER_URL_TEMPLATE")
PROXY_LIST_URL = CONFIG.get("PROXY_LIST_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}

class JetLink:
    def __init__(self, url, name=None, links=False, headers=None, inputstream=None):
        self.url = url
        self.name = name or url
        self.links = links
        self.headers = headers or {}
        self.inputstream = inputstream

class JetItem:
    def __init__(self, title, links=None, league=None, starttime=None, icon=None):
        self.title = title
        self.links = links or []
        self.league = league
        self.starttime = starttime
        self.icon = icon

@lru_cache(maxsize=1)
def get_working_proxy_list():
    print(f"🌍 Ambil daftar proxy dari: {PROXY_LIST_URL}")
    try:
        r = requests.get(PROXY_LIST_URL, timeout=10)
        r.raise_for_status()
        proxies = r.text.strip().splitlines()
        return [p.strip() for p in proxies if p.strip()]
    except Exception as e:
        print(f"❌ Gagal ambil daftar proxy: {e}")
        return []

def safe_get(url):
    print(f"🌐 Akses via proxy: {url}")
    for proxy_url in get_working_proxy_list():
        proxies = {"http": proxy_url, "https": proxy_url}
        try:
            print(f"🔁 Coba proxy: {proxy_url}")
            r = requests.get(url, headers=HEADERS, timeout=10, proxies=proxies, verify=False)
            r.raise_for_status()
            print(f"✅ Sukses proxy: {proxy_url}")
            return r.text
        except Exception as e:
            print(f"❌ Gagal: {proxy_url} - {e}")
            continue
    print(f"⛔ Semua proxy gagal untuk {url}")
    return None

def get_fixture_items():
    print("📺 Mengambil fixture...")
    items = []
    html = safe_get(f"https://{DOMAIN}/fixture/all.html")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    max_date = datetime.now() + timedelta(days=2)
    for game in soup.select("div.fixture-page-item"):
        try:
            team_left = game.select_one("span.name-team-left").text.strip()
            team_right = game.select_one("span.name-team-right").text.strip()
            title = f"{team_left} vs {team_right}"
            league = game.select_one("div.tournament").text.strip()
            ts = int(game.select_one(".time-format")["data-time"]) // 1000
            starttime = datetime.fromtimestamp(ts) + timedelta(hours=7)
            if starttime > max_date:
                continue
            href = game.select_one("a")["href"]
            url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(url, links=True)], league, starttime))
        except Exception as e:
            print(f"⚠️ Gagal parse fixture: {e}")
            continue
    print(f"✅ Total fixture: {len(items)}")
    return items

def get_upcoming_items():
    print("📺 Mengambil upcoming...")
    items = []
    html = safe_get(f"https://{DOMAIN}/upcoming.html")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    for match in soup.select("div.row-item-match"):
        try:
            left = match.select_one("span.name-team-left").text.strip()
            right = match.select_one("span.name-team-right").text.strip()
            title = f"{left} vs {right}"
            league = match.select_one("p.tour-name").text.strip()
            ts = int(match.select_one(".time-format")["data-time"]) // 1000
            starttime = datetime.fromtimestamp(ts) + timedelta(hours=7)
            href = match.select_one("a.btn-watch")["href"]
            url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(url, links=True)], league, starttime))
        except Exception as e:
            print(f"⚠️ Gagal parse upcoming: {e}")
            continue
    print(f"✅ Total upcoming: {len(items)}")
    return items

def clean_url(url):
    return url.replace('https://live-tv.vipcdn.live', M3U8_TEMPLATE_URL.split('/{channel_id}')[0])

def resolve_final_url_from_index(index_url):
    try:
        parts = urllib.parse.urlparse(index_url).path.strip("/").split("/")
        if parts:
            return M3U8_TEMPLATE_URL.format(channel_id=parts[0])
    except Exception as e:
        print(f"⚠️ Gagal konversi m3u8: {e}")
    return index_url

def get_links_from_live_page(url):
    print(f"🔗 Ambil link dari: {url}")
    html = safe_get(url)
    if not html:
        print("❌ Tidak bisa ambil halaman live")
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.select("a.link-channel"):
        raw = tag.get("data-url")
        if not raw:
            continue
        m3u8 = resolve_final_url_from_index(clean_url(raw))
        name = tag.text.strip()
        links.append(JetLink(m3u8, name=name, headers={
            "Referer": f"https://{DOMAIN}/",
            "User-Agent": HEADERS["User-Agent"],
            "Origin": f"https://{DOMAIN}"
        }))
    return links

def extract_channel_id(url):
    return urllib.parse.urlparse(url).path.strip("/").split("/")[0]

def save_to_m3u(items, filename="sayurasem.m3u"):
    lines = ["#EXTM3U"]
    for item in items:
        if not item.links:
            continue
        for link in item.links:
            cid = extract_channel_id(link.url)
            if not cid:
                continue
            tstr = item.starttime.astimezone(wib).strftime("%d/%m-%H.%M")
            title = f"{tstr} {item.title} - {link.name}"
            m3u = WORKER_URL_TEMPLATE.format(channel_id=cid)
            lines.append(f'#EXTINF:-1 tvg-logo="https://i.ibb.co/qY2HZWX5/512x512bb.jpg" group-title="\u26bd\ufe0f| LIVE EVENT",{title}')
            lines.append(m3u)
    Path(filename).write_text("\n".join(lines), encoding="utf-8")
    print(f"💾 Disimpan: {filename}")

def main():
    fixture = get_fixture_items()
    upcoming = get_upcoming_items()
    live_today = [i for i in fixture if i.starttime.date() == date.today()]

    print(f"\n📆 LIVE hari ini: {len(live_today)}")
    for i in live_today:
        print(f"🗓 {i.starttime} | {i.league} | {i.title}")
        i.links = get_links_from_live_page(i.links[0].url)

    print(f"\n📆 UPCOMING: {len(upcoming)}")
    for i in upcoming:
        print(f"🗓 {i.starttime} | {i.league} | {i.title}")
        i.links = get_links_from_live_page(i.links[0].url)

    save_to_m3u(live_today + upcoming)

if __name__ == "__main__":
    main()
