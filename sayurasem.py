import requests, urllib.parse
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from pytz import timezone
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

wib = timezone("Asia/Jakarta")

# ====== Load Konfigurasi ======
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

DOMAIN = CONFIG["DOMAIN"]
M3U8_TEMPLATE_URL = CONFIG["M3U8_TEMPLATE_URL"]
WORKER_URL_TEMPLATE = CONFIG["WORKER_URL_TEMPLATE"]
PROXY_LIST_URL = CONFIG["PROXY_LIST_URL"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}

class JetLink:
    def __init__(self, url, name=None, headers=None):
        self.url = url
        self.name = name or url
        self.headers = headers or {}

class JetItem:
    def __init__(self, title, links, league, starttime):
        self.title = title
        self.links = links
        self.league = league
        self.starttime = starttime

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

def parse_playing(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for m in soup.select("div.row-item-match"):
        try:
            t1 = m.select_one("span.name-team-left").text.strip()
            t2 = m.select_one("span.name-team-right").text.strip()
            title = f"{t1} vs {t2}"
            league = m.select_one("p.tour-name").text.strip()
            ts = int(m.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            href = m.select_one("a.btn-watch").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(full_url)], league, dt))
        except:
            continue
    return items

def parse_fixture(html, max_days=2):
    soup = BeautifulSoup(html, "html.parser")
    items, batas = [], datetime.now() + timedelta(days=max_days)
    for g in soup.select("div.fixture-page-item"):
        try:
            t1 = g.select_one("span.name-team-left").text
            t2 = g.select_one("span.name-team-right").text
            title = f"{t1} vs {t2}"
            league = g.select_one("div.tournament").text.strip()
            ts = int(g.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            if dt > batas: continue
            href = g.select_one("a").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(full_url)], league, dt))
        except: continue
    return items

def parse_upcoming(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for m in soup.select("div.row-item-match"):
        try:
            t1 = m.select_one("span.name-team-left").text.strip()
            t2 = m.select_one("span.name-team-right").text.strip()
            title = f"{t1} vs {t2}"
            league = m.select_one("p.tour-name").text.strip()
            ts = int(m.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=wib)
            href = m.select_one("a.btn-watch").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(full_url)], league, dt))
        except: continue
    return items

def clean_url(url):
    return url.replace("https://live-tv.vipcdn.live", M3U8_TEMPLATE_URL.split("/{channel_id}")[0])

def resolve_m3u8(url):
    try:
        path = urllib.parse.urlparse(url).path.strip("/")
        cid = path.split("/")[0]
        return M3U8_TEMPLATE_URL.format(channel_id=cid), cid
    except: return url, None

def get_links(live_url, proxies):
    html = safe_get(live_url, proxies)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.select("a.link-channel"):
        raw = tag.get("data-url")
        if not raw: continue
        name = tag.text.strip()
        final_url, _ = resolve_m3u8(clean_url(raw))
        agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 13_1_2 like Mac OS X)" if "score806" in final_url else HEADERS["User-Agent"]
        links.append(JetLink(final_url, name, headers={"Referer": f"https://{DOMAIN}/", "User-Agent": agent}))
    return links

def save_to_m3u(items, file="sayurasem.m3u"):
    lines = ["#EXTM3U"]
    for item in items:
        for link in item.links:
            _, cid = resolve_m3u8(link.url)
            if not cid: continue
            waktu = item.starttime.strftime("%d/%m-%H.%M")
            nama = f"{waktu} {item.title} - {link.name}"
            logo = "https://i.ibb.co/qY2HZWX5/512x512bb.jpg"
            group = "⚽️| LIVE EVENT"
            stream_url = WORKER_URL_TEMPLATE.format(channel_id=cid)
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{nama}')
            lines.append(stream_url)
    Path(file).write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ M3U disimpan: {file}")

def main():
    proxies = load_proxies()
    if not proxies:
        print("❌ Tidak ada proxy tersedia.")
        return

    fixture_html = safe_get(f"https://{DOMAIN}/fixture/all.html", proxies)
    upcoming_html = safe_get(f"https://{DOMAIN}/upcoming.html", proxies)
    playing_html = safe_get(f"https://{DOMAIN}/playing.html", proxies)

    fixtures = parse_fixture(fixture_html) if fixture_html else []
    upcoming = parse_upcoming(upcoming_html) if upcoming_html else []
    playing = parse_playing(playing_html) if playing_html else []

    today = [f for f in fixtures if f.starttime.date() == date.today()]
    focus = today + upcoming + playing

    print(f"\n📆 Total Pertandingan: {len(focus)}")
    for item in focus:
        print(f"🕒 {item.starttime.strftime('%d/%m %H:%M')} | {item.league} | {item.title}")
        item.links = get_links(item.links[0].url, proxies)

    save_to_m3u(focus)

if __name__ == "__main__":
    main()
