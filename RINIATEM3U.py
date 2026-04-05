from zoneinfo import ZoneInfo
from datetime import datetime
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
DOMAIN = CONFIG["DOMAIN"]
AESPORT_WORKER_TEMPLATE2 = CONFIG["AESPORT_WORKER_TEMPLATE2"]
AESPORT_LOGO = CONFIG["AESPORT_LOGO"]
AESPORT_TIMEOUT = CONFIG.get("AESPORT_TIMEOUT", 10)
GROUP = CONFIG["GROUP"]

AESPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": f"https://{DOMAIN}/",
    "Origin": f"https://{DOMAIN}"
}

SESSION = requests.Session()
SESSION.headers.update(AESPORT_HEADERS)

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
    url = f"https://{AESPORT_DOMAIN}/upcoming.html"

    r = SESSION.get(url, timeout=AESPORT_TIMEOUT, verify=False)
    if r.status_code != 200:
        print("❌ Gagal ambil upcoming")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    matches = soup.select('a[href^="/match/"]')

    print(f"🎯 Match ditemukan: {len(matches)}")

    for m in matches:
        try:
            teams = m.select("p")
            if len(teams) < 2:
                continue

            home = teams[0].text.strip()
            away = teams[1].text.strip()

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
            continue

    return items

# ==========================
# 🔴 PLAYING
# ==========================
def parse_playing():
    print("🔴 Mengambil playing (live now)...")
    url = f"https://{AESPORT_DOMAIN}/playing.html"

    r = SESSION.get(url, timeout=AESPORT_TIMEOUT, verify=False)
    if r.status_code != 200:
        print("❌ Gagal ambil playing")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    matches = soup.select('a[href^="/match/"]')

    print(f"🎯 LIVE ditemukan: {len(matches)}")

    for m in matches:
        try:
            teams = m.select("p")
            if len(teams) < 2:
                continue

            home = teams[0].text.strip()
            away = teams[1].text.strip()

            time_tag = m.select_one("[data-match-time]")
            if time_tag:
                utc_time = time_tag.get("data-utc")
                dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
                dt = dt.astimezone(ZoneInfo("Asia/Jakarta"))
            else:
                dt = datetime.now(ZoneInfo("Asia/Jakarta"))

            slug = m.get("href").split("/")[-1]

            items.append(JetItem(
                f"{home} vs {away}",
                slug,
                "LIVE",
                dt
            ))

        except Exception as e:
            print("Parse error:", e)
            continue

    return items

# ==========================
# 🎯 MAIN MATCH COLLECTOR
# ==========================
def get_aesport_matches():
    upcoming_items = parse_upcoming()
    playing_items = parse_playing()

    print("DEBUG upcoming:", len(upcoming_items))
    print("DEBUG playing:", len(playing_items))

    all_items = playing_items + upcoming_items

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
        print("⚠️ Tidak ada match ditemukan.")
        return

    outfile = Path("matama.m3u")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(matches))

    print(f"✅ Berhasil generate {outfile} dengan {len(matches)} channel")

if __name__ == "__main__":
    main()
