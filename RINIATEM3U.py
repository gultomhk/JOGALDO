from zoneinfo import ZoneInfo
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import urllib3
import json
import html

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================
# 🔧 Load CONFIG
# ==========================
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

AESPORT_DOMAIN = CONFIG["AESPORT_DOMAIN"]  # domain worker
DOMAIN = CONFIG["DOMAIN"]
AESPORT_WORKER_TEMPLATE2 = CONFIG["AESPORT_WORKER_TEMPLATE2"]
AESPORT_LOGO = CONFIG["AESPORT_LOGO"]
AESPORT_TIMEOUT = CONFIG.get("AESPORT_TIMEOUT", 10)
GROUP = CONFIG["GROUP"]

AESPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9"
}

SESSION = requests.Session()
SESSION.headers.update(AESPORT_HEADERS)

# ==========================
# 🌐 REQUEST (NO PROXY)
# ==========================
def safe_get(url):
    try:
        r = SESSION.get(
            url,
            timeout=AESPORT_TIMEOUT,
            verify=False
        )

        if r.status_code == 200:
            print(f"✅ OK {url}")
            return r.text
        else:
            print(f"⚠️ Status {r.status_code} {url}")
            return None

    except Exception as e:
        print(f"❌ Error {url}:", e)
        return None


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
# 📅 UPCOMING
# ==========================
def parse_upcoming():
    print("📅 Mengambil upcoming...")
    url = f"https://{AESPORT_DOMAIN}/upcoming"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    matches = soup.select('a[href^="/match/"]')

    print(f"🎯 Match ditemukan: {len(matches)}")

    for m in matches:
        try:
            teams = [p.get_text(strip=True) for p in m.select("p") if p.get_text(strip=True)]
            if len(teams) < 2:
                continue

            home, away = teams[:2]

            time_tag = m.select_one("[data-match-time]")
            if not time_tag:
                continue

            utc_time = time_tag.get("data-utc")
            dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
            dt = dt.astimezone(ZoneInfo("Asia/Jakarta"))

            slug = m.get("href").split("/")[-1]

            items.append(JetItem(
                f"{home} vs {away}",
                slug,
                "",
                dt
            ))

        except Exception as e:
            print("Parse error:", e)

    return items


# ==========================
# 🔴 LIVE
# ==========================
def parse_playing():
    print("🔴 Mengambil playing...")
    url = f"https://{AESPORT_DOMAIN}/live-now"
    html_text = safe_get(url)
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    items = []

    island = soup.find("astro-island")
    if not island:
        print("❌ Tidak menemukan astro-island live data")
        return []

    props_raw = island.get("props")
    props_raw = html.unescape(props_raw)

    try:
        data = json.loads(props_raw)
        matches = data["initialItems"][1]

        print(f"🎯 LIVE JSON ditemukan: {len(matches)}")

        for m in matches:
            obj = m[1]

            home = obj["name_home"]
            away = obj["name_away"]
            slug = obj["slug"]
            start_at = obj["start_at"]

            dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            dt = dt.astimezone(ZoneInfo("Asia/Jakarta"))

            items.append(JetItem(
                f"{home} vs {away}",
                slug,
                "LIVE",
                dt
            ))

    except Exception as e:
        print("Parse LIVE JSON error:", e)

    return items


# ==========================
# 🎯 COMBINE
# ==========================
def get_aesport_matches():
    upcoming_items = parse_upcoming()
    playing_items = parse_playing()

    print("DEBUG upcoming:", len(upcoming_items))
    print("DEBUG playing:", len(playing_items))

    unique = {}

    # LIVE priority
    for item in playing_items:
        unique[item.slug] = item

    # Upcoming if not exist
    for item in upcoming_items:
        if item.slug not in unique:
            unique[item.slug] = item

    outputs = []

    for item in unique.values():
        waktu = item.starttime.strftime("%d/%m-%H.%M")

        nama = f"{waktu} {item.title}"
        stream_url = AESPORT_WORKER_TEMPLATE2.format(slug=item.slug)

        outputs.append("\n".join([
            f'#EXTINF:-1 tvg-logo="{AESPORT_LOGO}" group-title="{GROUP}",{nama}',
            f'#EXTVLCOPT:http-user-agent={AESPORT_HEADERS["User-Agent"]}',
            f'#EXTVLCOPT:http-referrer={AESPORT_HEADERS["Referer"]}',
            stream_url
        ]))

    return outputs

# ==========================
# 📝 MAIN
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
