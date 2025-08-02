import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from pytz import timezone
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Zona waktu
wib = timezone("Asia/Jakarta")

# ====== Load Konfigurasi ======
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

DOMAIN = CONFIG["DOMAIN"]
TIMEOUT = CONFIG.get("TIMEOUT", 20)
PROXY = CONFIG.get("PROXY")
HEADERS = {
    "User-Agent": CONFIG.get("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}
WORKER_TEMPLATE2 = CONFIG["WORKER_URL_TEMPLATE2"]

class JetItem:
    def __init__(self, title, slug, league, starttime):
        self.title = title
        self.slug = slug
        self.league = league
        self.starttime = starttime

def safe_get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, proxies=PROXY, verify=False)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠️ Gagal ambil {url}: {e}")
        return None

def parse_fixture():
    print("📺 Mengambil fixture...")
    url = f"https://{DOMAIN}/fixture/all.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    max_date = datetime.now(wib) + timedelta(days=2)
    for game in soup.select("div.fixture-page-item"):
        try:
            t1 = game.select_one("span.name-team-left").text.strip()
            t2 = game.select_one("span.name-team-right").text.strip()
            title = f"{t1} vs {t2}"
            league = game.select_one("div.tournament").text.strip()
            ts = int(game.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            if dt > max_date:
                continue
            href = game.select_one("a").get("href")
            slug = href.split("/")[-1].replace(".html", "")
            items.append(JetItem(title, slug, league, dt))
        except Exception as e:
            print(f"⚠️ Error parsing fixture: {e}")
            continue
    return items

def parse_upcoming():
    print("📺 Mengambil upcoming...")
    url = f"https://{DOMAIN}/upcoming.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    for match in soup.select("div.row-item-match"):
        try:
            t1 = match.select_one("span.name-team-left").text.strip()
            t2 = match.select_one("span.name-team-right").text.strip()
            title = f"{t1} vs {t2}"
            league = match.select_one("p.tour-name").text.strip()
            ts = int(match.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            href = match.select_one("a.btn-watch").get("href")
            slug = href.split("/")[-1].replace(".html", "")
            items.append(JetItem(title, slug, league, dt))
        except Exception as e:
            print(f"⚠️ Error parsing upcoming: {e}")
            continue
    return items

def save_to_m3u(items, filename="jajang.m3u"):
    lines = ["#EXTM3U"]
    logo = CONFIG.get("LOGO_URL", "https://i.ibb.co/qY2HZWX5/512x512bb.jpg")
    group = CONFIG.get("GROUP_NAME", "⚽️| LIVE EVENT")
    for item in items:
        waktu = item.starttime.astimezone(wib).strftime("%d/%m-%H.%M")
        nama = f"{waktu} {item.title}"
        stream_url = WORKER_TEMPLATE2.format(slug=item.slug)
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{nama}')
        lines.append(stream_url)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Playlist M3U disimpan: {filename}")

def main():
    fixture_items = parse_fixture()
    upcoming_items = parse_upcoming()

    today_items = [i for i in fixture_items if i.starttime.date() == date.today()]
    all_items = today_items + upcoming_items

    print(f"\n📆 Total pertandingan ditemukan: {len(all_items)}")
    for item in all_items:
        print(f"🕒 {item.starttime.strftime('%d/%m %H:%M')} | {item.title} ({item.slug})")

    save_to_m3u(all_items)

if __name__ == "__main__":
    main()
