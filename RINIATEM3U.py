import requests
import re
import base64, json, binascii
from datetime import datetime, timedelta, date
from dateutil import tz
from zoneinfo import ZoneInfo
import html
from pytz import timezone
from bs4 import BeautifulSoup
import urllib.parse
import urllib3
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 🔧 Load AESPORT config
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

AESPORT_DOMAIN = CONFIG["AESPORT_DOMAIN"]
AESPORT_PROXY = CONFIG["AESPORT_PROXY"]
AESPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"https://{AESPORT_DOMAIN}/",
    "Origin": f"https://{AESPORT_DOMAIN}"
}
AESPORT_WORKER_TEMPLATE2 = CONFIG["AESPORT_WORKER_TEMPLATE2"]
AESPORT_LOGO = CONFIG["AESPORT_LOGO"]
AESPORT_TIMEOUT = CONFIG.get("AESPORT_TIMEOUT", 20)
GROUP = CONFIG["GROUP"]


class JetItem:
    def __init__(self, title, slug, league, starttime):
        self.title = title
        self.slug = slug
        self.league = league
        self.starttime = starttime

def safe_get(url):
    try:
        r = requests.get(url, headers=AESPORT_HEADERS, timeout=AESPORT_TIMEOUT, proxies=AESPORT_PROXY, verify=False)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠️ Gagal ambil {url}: {e}")
        return None

def parse_fixture():
    print("📺 Mengambil fixture dari aesport.tv...")
    url = f"https://{AESPORT_DOMAIN}/fixture/all.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    max_date = datetime.now(timezone("Asia/Jakarta")) + timedelta(days=2)
    for game in soup.select("div.fixture-page-item"):
        try:
            t1 = game.select_one("span.name-team-left").text.strip()
            t2 = game.select_one("span.name-team-right").text.strip()
            title = f"{t1} vs {t2}"
            league = game.select_one("div.tournament").text.strip()
            ts = int(game.select_one(".time-format")["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=timezone("Asia/Jakarta"))
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
    print("📺 Mengambil upcoming dari aesport.tv...")
    url = f"https://{AESPORT_DOMAIN}/upcoming.html"
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
            dt = datetime.fromtimestamp(ts, tz=timezone("Asia/Jakarta"))
            href = match.select_one("a.btn-watch").get("href")
            slug = href.split("/")[-1].replace(".html", "")
            items.append(JetItem(title, slug, league, dt))
        except Exception as e:
            print(f"⚠️ Error parsing upcoming: {e}")
            continue
    return items

def get_aesport_matches():
    fixture_items = parse_fixture()
    upcoming_items = parse_upcoming()

    today_items = [i for i in fixture_items if i.starttime.date() == date.today()]
    all_items = today_items + upcoming_items

    # 🚨 Hapus duplikat berdasarkan slug
    unique = {}
    for item in all_items:
        unique[item.slug] = item  # overwrite kalau ada slug sama

    outputs = []
    for item in unique.values():
        waktu = item.starttime.astimezone(timezone("Asia/Jakarta")).strftime("%d/%m-%H.%M")
        nama = f"{waktu} {item.title}"
        stream_url = AESPORT_WORKER_TEMPLATE2.format(slug=item.slug)
        line = [
            f'#EXTINF:-1 tvg-logo="{AESPORT_LOGO}" group-title="{GROUP}",{nama}',
            stream_url
        ]
        outputs.append("\n".join(line))

    return outputs

def main():
    matches = get_aesport_matches()
    outfile = Path("matama.m3u")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(matches))
    print(f"✅ Berhasil generate {outfile} dengan {len(matches)} channel")

if __name__ == "__main__":
    main()
