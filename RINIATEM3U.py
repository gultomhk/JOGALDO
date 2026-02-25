from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, date
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================
# 🔧 Load CONFIG
# ==========================
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

AESPORT_DOMAIN = CONFIG["AESPORT_DOMAIN"]
AESPORT_PROXY = CONFIG.get("AESPORT_PROXY", None)
AESPORT_WORKER_TEMPLATE2 = CONFIG["AESPORT_WORKER_TEMPLATE2"]
AESPORT_LOGO = CONFIG["AESPORT_LOGO"]
AESPORT_TIMEOUT = CONFIG.get("AESPORT_TIMEOUT", 20)
GROUP = CONFIG["GROUP"]

AESPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": f"https://{AESPORT_DOMAIN}/",
    "Origin": f"https://{AESPORT_DOMAIN}"
}


# ==========================
# 📦 MODEL
# ==========================
class JetItem:
    def __init__(self, title, slug, league, starttime):
        self.title = title
        self.slug = slug
        self.league = league
        self.starttime = starttime


# ==========================
# 🌐 SAFE REQUEST
# ==========================
def safe_get(url):
    try:
        r = requests.get(
            url,
            headers=AESPORT_HEADERS,
            timeout=AESPORT_TIMEOUT,
            proxies=AESPORT_PROXY,
            verify=False
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠️ Gagal ambil {url}: {e}")
        return None


# ==========================
# 📺 FIXTURE
# ==========================
def parse_fixture():
    print("📺 Mengambil fixture...")
    url = f"https://{AESPORT_DOMAIN}/fixture/all.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    max_date = datetime.now(ZoneInfo("Asia/Jakarta")) + timedelta(days=2)

    for game in soup.select("div.fixture-page-item"):
        try:
            left = game.select_one("span.name-team-left")
            right = game.select_one("span.name-team-right")
            timeTag = game.select_one(".time-format")
            link = game.select_one("a[href*='/live/']")

            if not (left and right and timeTag and link):
                continue

            ts = int(timeTag["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Jakarta"))

            if dt > max_date:
                continue

            slug = link.get("href").split("/")[-1].replace(".html", "")
            leagueTag = game.select_one("div.tournament")

            items.append(
                JetItem(
                    f"{left.text.strip()} vs {right.text.strip()}",
                    slug,
                    leagueTag.text.strip() if leagueTag else "",
                    dt
                )
            )
        except Exception as e:
            print(f"⚠️ Error parsing fixture: {e}")
            continue

    return items


# ==========================
# 📅 UPCOMING
# ==========================
def parse_upcoming():
    print("📅 Mengambil upcoming...")
    url = f"https://{AESPORT_DOMAIN}/upcoming.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    for match in soup.select("div.row-item-match"):
        try:
            left = match.select_one("span.name-team-left")
            right = match.select_one("span.name-team-right")
            timeTag = match.select_one(".time-format")
            link = match.select_one("a.btn-watch")

            if not (left and right and timeTag and link):
                continue

            ts = int(timeTag["data-time"]) // 1000
            dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Jakarta"))

            slug = link.get("href").split("/")[-1].replace(".html", "")
            leagueTag = match.select_one("p.tour-name")

            items.append(
                JetItem(
                    f"{left.text.strip()} vs {right.text.strip()}",
                    slug,
                    leagueTag.text.strip() if leagueTag else "",
                    dt
                )
            )
        except Exception as e:
            print(f"⚠️ Error parsing upcoming: {e}")
            continue

    return items


# ==========================
# 🔴 PLAYING (LIVE NOW)
# ==========================
def parse_playing():
    print("🔴 Mengambil playing (live now)...")
    url = f"https://{AESPORT_DOMAIN}/playing.html"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    for match in soup.select("div.row-item-match, div.fixture-page-item"):
        try:
            left = match.select_one("span.name-team-left")
            right = match.select_one("span.name-team-right")
            link = match.select_one("a[href*='/live/']")

            if not (left and right and link):
                continue

            slug = link.get("href").split("/")[-1].replace(".html", "")

            # Jika tidak ada timestamp → pakai waktu sekarang
            timeTag = match.select_one(".time-format")
            if timeTag and timeTag.has_attr("data-time"):
                ts = int(timeTag["data-time"]) // 1000
                dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Jakarta"))
            else:
                dt = datetime.now(ZoneInfo("Asia/Jakarta"))

            leagueTag = match.select_one("p.tour-name, div.tournament")

            items.append(
                JetItem(
                    f"{left.text.strip()} vs {right.text.strip()}",
                    slug,
                    leagueTag.text.strip() if leagueTag else "LIVE",
                    dt
                )
            )
        except Exception as e:
            print(f"⚠️ Error parsing playing: {e}")
            continue

    return items


# ==========================
# 🎯 MAIN MATCH COLLECTOR
# ==========================
def get_aesport_matches():

    fixture_items = parse_fixture()
    upcoming_items = parse_upcoming()
    playing_items = parse_playing()

    today_items = [
        i for i in fixture_items
        if i.starttime.date() == date.today()
    ]

    all_items = playing_items + today_items + upcoming_items

    # 🚨 Remove duplicate slug
    unique = {}
    for item in all_items:
        unique[item.slug] = item

    outputs = []

    for item in unique.values():
        waktu = item.starttime.astimezone(
            ZoneInfo("Asia/Jakarta")
        ).strftime("%d/%m-%H.%M")

        nama = f"{waktu} {item.title}"
        stream_url = AESPORT_WORKER_TEMPLATE2.format(slug=item.slug)

        line = [
            f'#EXTINF:-1 tvg-logo="{AESPORT_LOGO}" group-title="{GROUP}",{nama}',
            f'#EXTVLCOPT:http-user-agent={AESPORT_HEADERS["User-Agent"]}',
            f'#EXTVLCOPT:http-referrer={AESPORT_HEADERS["Referer"]}',
            stream_url
        ]

        outputs.append("\n".join(line))

    return outputs


# ==========================
# 📝 GENERATE M3U
# ==========================
def main():
    matches = get_aesport_matches()

    if not matches:
        print("⚠️ Tidak ada match ditemukan, skip generate file.")
        return

    outfile = Path("matama.m3u")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(matches))

    print(f"✅ Berhasil generate {outfile} dengan {len(matches)} channel")


if __name__ == "__main__":
    main()
