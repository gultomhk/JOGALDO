import requests, urllib.parse, json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from pytz import timezone
from pathlib import Path
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Zona waktu
wib = timezone("Asia/Jakarta")

# ====== Load Konfigurasi ======
CONFIG_FILE = Path.home() / "aebabami_file.txt"
CONFIG = {}
exec(CONFIG_FILE.read_text(encoding="utf-8"), CONFIG)

DOMAIN = CONFIG["DOMAIN"]
M3U8_TEMPLATE_URL = CONFIG["M3U8_TEMPLATE_URL"]
WORKER_URL_TEMPLATE = CONFIG["WORKER_URL_TEMPLATE"]
PROXY_LIST_URL = CONFIG["PROXY_LIST_URL"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}

# ====== Kelas ======
class JetLink:
    def __init__(self, url, name=None, links=False, headers=None):
        self.url = url
        self.name = name or url
        self.links = links
        self.headers = headers or {}

class JetItem:
    def __init__(self, title, links=None, league=None, starttime=None, icon=None):
        self.title = title
        self.links = links or []
        self.league = league
        self.starttime = starttime
        self.icon = icon

# ====== Proxy Loader ======
def load_proxy_list():
    try:
        print(f"🌐 Ambil proxy list dari: {PROXY_LIST_URL}")
        resp = requests.get(PROXY_LIST_URL, timeout=10)
        resp.raise_for_status()
        proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
        print(f"✅ {len(proxies)} proxy ditemukan.")
        return proxies
    except Exception as e:
        print(f"⚠️ Gagal ambil proxy list: {e}")
        return []

# ====== Safe GET ======
def safe_get(url, proxies):
    for proxy_url in proxies:
        proxy = {
            "http": proxy_url,
            "https": proxy_url
        }
        try:
            r = requests.get(url, headers=HEADERS, timeout=10, proxies=proxy, verify=False)
            print(f"↪️ {url} via {proxy_url} => {r.status_code}")
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"❌ Proxy gagal: {proxy_url} ({e})")
            continue
    print(f"❌ Semua proxy gagal untuk {url}")
    return None

# ====== Fixture & Upcoming Parser ======
def parse_fixture(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    max_date = datetime.now() + timedelta(days=2)
    for game in soup.select("div.fixture-page-item"):
        try:
            left = game.select_one("span.name-team-left").text
            right = game.select_one("span.name-team-right").text
            title = f"{left} vs {right}"
            league = game.select_one("div.tournament").text.strip()
            timestamp = int(game.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(timestamp, tz=wib)
            if dt > max_date:
                continue
            href = game.select_one("a").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(full_url, links=True)], league, dt))
        except:
            continue
    return items

def parse_upcoming(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for match in soup.select("div.row-item-match"):
        try:
            left = match.select_one("span.name-team-left").text.strip()
            right = match.select_one("span.name-team-right").text.strip()
            title = f"{left} vs {right}"
            league = match.select_one("p.tour-name").text.strip()
            timestamp = int(match.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(timestamp, tz=wib)
            href = match.select_one("a.btn-watch").get("href")
            full_url = href if href.startswith("http") else f"https://{DOMAIN}{href}"
            items.append(JetItem(title, [JetLink(full_url, links=True)], league, dt))
        except:
            continue
    return items

# ====== M3U8 Handler ======
def clean_url(url):
    return url.replace("https://live-tv.vipcdn.live", M3U8_TEMPLATE_URL.split("/{channel_id}")[0])

def resolve_final_url(index_url):
    try:
        parts = urllib.parse.urlparse(index_url).path.strip("/").split("/")
        if parts: return M3U8_TEMPLATE_URL.format(channel_id=parts[0])
    except: pass
    return index_url

def extract_channel_id(url):
    try:
        return urllib.parse.urlparse(url).path.strip("/").split("/")[0]
    except: return None

def get_links_from_live(url, proxies):
    print(f"🔗 Ambil link dari: {url}")
    html = safe_get(url, proxies)
    if not html:
        print("❌ Gagal ambil halaman live.")
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.select("a.link-channel"):
        raw_url = tag.get("data-url")
        if not raw_url:
            continue
        m3u8_url = resolve_final_url(clean_url(raw_url))
        name = tag.text.strip()
        user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 13_1_2 like Mac OS X)" if "score806" in m3u8_url else HEADERS["User-Agent"]
        links.append(JetLink(m3u8_url, name, headers={
            "Referer": f"https://{DOMAIN}/",
            "User-Agent": user_agent,
            "Origin": f"https://{DOMAIN}"
        }))
    return links

# ====== M3U Generator ======
def save_to_m3u(items, filename="sayurasem.m3u"):
    lines = ["#EXTM3U"]
    for item in items:
        if not item.links: continue
        for link in item.links:
            cid = extract_channel_id(link.url)
            if not cid: continue
            waktu = item.starttime.strftime("%d/%m-%H.%M")
            logo = "https://i.ibb.co/qY2HZWX5/512x512bb.jpg"
            group = "⚽️| LIVE EVENT"
            nama = f"{waktu} {item.title} - {link.name}"
            url = WORKER_URL_TEMPLATE.format(channel_id=cid)
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{nama}')
            lines.append(url)
    Path(filename).write_text("\n".join(lines), encoding="utf-8")
    print(f"💾 Disimpan: {filename}")

# ====== MAIN ======
def main():
    proxies = load_proxy_list()

    fixture_html = safe_get(f"https://{DOMAIN}/fixture/all.html", proxies)
    upcoming_html = safe_get(f"https://{DOMAIN}/upcoming.html", proxies)

    fixture_items = parse_fixture(fixture_html) if fixture_html else []
    upcoming_items = parse_upcoming(upcoming_html) if upcoming_html else []

    today_items = [i for i in fixture_items if i.starttime.date() == date.today()]
    all_focus_items = today_items + upcoming_items

    print(f"\n📺 Total pertandingan: {len(all_focus_items)}")
    for item in all_focus_items:
        print(f"🗓 {item.starttime.strftime('%d/%m %H:%M')} | {item.league} | {item.title}")
        item.links = get_links_from_live(item.links[0].url, proxies)

    save_to_m3u(all_focus_items, "sayurasem.m3u")

if __name__ == "__main__":
    main()
