import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
import json
import urllib.parse
from pytz import timezone
from pathlib import Path

# Zona waktu
wib = timezone("Asia/Jakarta")

# ====== Konfigurasi Dinamis ======
AEBABAMI_FILE = Path.home() / "aebabami_file.txt"
CONFIG = {}

with open(AEBABAMI_FILE, "r", encoding="utf-8") as f:
    exec(f.read(), CONFIG)

DOMAIN = CONFIG.get("DOMAIN")
M3U8_TEMPLATE_URL = CONFIG.get("M3U8_TEMPLATE_URL")
WORKER_URL_TEMPLATE = CONFIG.get("WORKER_URL_TEMPLATE")

TIMEOUT = 15

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

def safe_get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠️ Gagal ambil {url}: {e}")
        return None

def get_fixture_items():
    print("📺 Mengambil fixture...")
    items = []
    url = f"https://{DOMAIN}/fixture/all.html"

    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    max_date = datetime.now() + timedelta(days=2)
    for game in soup.select("div.fixture-page-item"):
        try:
            team_left = game.select_one("span.name-team-left").text
            team_right = game.select_one("span.name-team-right").text
            title = f"{team_left} vs {team_right}"
            league = game.select_one("div.tournament").text.strip()
            utc_time = datetime.fromtimestamp(int(game.select_one(".time-format").get("data-time")) // 1000) + timedelta(hours=7)
            if utc_time > max_date:
                continue
            href = game.select_one("a").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, links=[JetLink(full_url, links=True)], league=league, starttime=utc_time))
        except Exception as e:
            print("⚠️ Gagal parse fixture:", e)
            continue

    print(f"✅ Total fixture ditemukan: {len(items)}")
    return items

def get_upcoming_items():
    print("📺 Mengambil upcoming...")
    items = []
    url = f"https://{DOMAIN}/upcoming.html"

    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    for match in soup.select("div.row-item-match"):
        try:
            left = match.select_one("span.name-team-left").text.strip()
            right = match.select_one("span.name-team-right").text.strip()
            title = f"{left} vs {right}"
            league = match.select_one("p.tour-name").text.strip()
            timestamp = int(match.select_one(".time-format").get("data-time")) // 1000
            utc_time = datetime.fromtimestamp(timestamp) + timedelta(hours=7)
            href = match.select_one("a.btn-watch").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, links=[JetLink(full_url, links=True)], league=league, starttime=utc_time))
        except Exception as e:
            print("⚠️ Gagal parse upcoming:", e)
            continue

    print(f"✅ Total upcoming ditemukan: {len(items)}")
    return items

def clean_url(url: str) -> str:
    return url.replace('https://live-tv.vipcdn.live', M3U8_TEMPLATE_URL.split("/{channel_id}")[0])

def resolve_final_url_from_index(index_url):
    try:
        parsed = urllib.parse.urlparse(index_url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 1:
            channel_id = parts[0]
            return M3U8_TEMPLATE_URL.format(channel_id=channel_id)
    except Exception as e:
        print(f"⚠️ Gagal konstruksi final m3u8 dari {index_url}: {e}")
    return index_url

def get_links_from_live_page(url):
    print(f"🔗 Ambil link dari: {url}")
    html = safe_get(url)
    if not html:
        print("❌ Gagal ambil halaman live.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.select("a.link-channel"):
        raw_url = tag.get("data-url")
        if not raw_url:
            continue
        m3u8_url = resolve_final_url_from_index(clean_url(raw_url))
        name = tag.text.strip()
        user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 13_1_2 like Mac OS X)" if "score806" in m3u8_url else HEADERS["User-Agent"]
        links.append(JetLink(m3u8_url, name=name, headers={
            "Referer": f"https://{DOMAIN}/",
            "User-Agent": user_agent,
            "Origin": f"https://{DOMAIN}"
        }))
    return links

def extract_channel_id(url):
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parts:
        return parts[0]
    return None

def save_to_m3u(items, filename="all.m3u"):
    lines = ["#EXTM3U"]
    for item in items:
        if not item.links:
            continue
        for link in item.links:
            channel_id = extract_channel_id(link.url)
            if not channel_id:
                continue

            time_str = item.starttime.astimezone(wib).strftime("%d/%m-%H.%M")
            title_line = f'{time_str} {item.title} - {link.name}'
            logo = "https://i.ibb.co/qY2HZWX5/512x512bb.jpg"
            group = "⚽️| LIVE EVENT"
            worker_url = WORKER_URL_TEMPLATE.format(channel_id=channel_id)

            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{title_line}')
            lines.append(worker_url)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"💾 Playlist M3U disimpan ke {filename}")

def is_today(dt):
    return dt.date() == date.today()

def main():
    fixture_items = get_fixture_items()
    upcoming_items = get_upcoming_items()

    today_items = [i for i in fixture_items if is_today(i.starttime)]

    print(f"\n📆 Pertandingan LIVE hari ini: {len(today_items)}")
    for item in today_items:
        print(f"🗓 {item.starttime} | {item.league} | {item.title}")
        item.links = get_links_from_live_page(item.links[0].url)

    print(f"\n📆 Pertandingan UPCOMING: {len(upcoming_items)}")
    for item in upcoming_items:
        print(f"🗓 {item.starttime} | {item.league} | {item.title}")
        item.links = get_links_from_live_page(item.links[0].url)

    all_focus_items = today_items + upcoming_items

    save_to_m3u(all_focus_items, "sayurasem.m3u")

if __name__ == "__main__":
    main()
