from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, date
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import urllib3
import random

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================
# 🔧 Load CONFIG
# ==========================
CONFIG = {}
exec((Path.home() / "aebabami_file.txt").read_text(encoding="utf-8"), CONFIG)

AESPORT_DOMAIN = CONFIG["AESPORT_DOMAIN"]
AESPORT_WORKER_TEMPLATE2 = CONFIG["AESPORT_WORKER_TEMPLATE2"]
AESPORT_LOGO = CONFIG["AESPORT_LOGO"]
AESPORT_TIMEOUT = CONFIG.get("AESPORT_TIMEOUT", 10)
GROUP = CONFIG["GROUP"]

PROXY_SOURCE = CONFIG["PROXY_SOURCE"]

AESPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": f"https://{AESPORT_DOMAIN}/",
    "Origin": f"https://{AESPORT_DOMAIN}"
}

# ==========================
# 🌐 LOAD PROXY LIST
# ==========================
def load_proxies():
    print("🌐 Mengambil proxy list...")
    try:
        r = requests.get(PROXY_SOURCE, timeout=20)
        r.raise_for_status()

        proxies = [p.strip() for p in r.text.splitlines() if p.strip()]
        random.shuffle(proxies)

        proxy_list = [{
            "http": f"http://{p}",
            "https": f"http://{p}"
        } for p in proxies]

        print(f"✅ Proxy ditemukan: {len(proxy_list)}")
        return proxy_list

    except Exception as e:
        print(f"⚠️ Gagal ambil proxylist: {e}")
        return []


PROXIES = load_proxies()

# ==========================
# 🌐 SESSION + ACTIVE PROXY
# ==========================
SESSION = requests.Session()
SESSION.headers.update(AESPORT_HEADERS)

ACTIVE_PROXY = None


def get_working_proxy(test_url):
    global ACTIVE_PROXY

    print("🔎 Mencari proxy yang bisa dipakai...")

    for proxy in PROXIES:
        try:
            r = SESSION.get(
                test_url,
                timeout=AESPORT_TIMEOUT,
                proxies=proxy,
                verify=False,
                allow_redirects=True
            )

            if r.status_code in [200, 301, 302]:
                ACTIVE_PROXY = proxy
                print(f"✅ Proxy aktif: {proxy['http']}")
                return True

        except Exception:
            continue

    print("❌ Tidak ada proxy yang berhasil")
    return False


# ==========================
# 🌐 SAFE REQUEST (PROXY ONLY)
# ==========================
def safe_get(url):
    global ACTIVE_PROXY

    if not ACTIVE_PROXY:
        if not get_working_proxy(url):
            return None

    try:
        r = SESSION.get(
            url,
            timeout=AESPORT_TIMEOUT,
            proxies=ACTIVE_PROXY,
            verify=False,
            allow_redirects=True
        )

        if r.status_code == 200:
            print(f"✅ OK {url}")
            return r.text
        else:
            print(f"⚠️ Status {r.status_code}, ganti proxy...")
            ACTIVE_PROXY = None
            return safe_get(url)

    except Exception:
        print("⚠️ Proxy mati, cari proxy baru...")
        ACTIVE_PROXY = None
        return safe_get(url)


# ==========================
# 📦 MODEL
# ==========================
class JetItem:
    def __init__(self, title, slug, league, starttime):
        self.title = title
        self.slug = slug
        self.league = league
        self.starttime = starttime

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

            href = m.get("href")
            slug = href.split("/")[-1]

            items.append(JetItem(
                f"{home} vs {away}",
                slug,
                "",  # league sementara kosong (opsional bisa kita parse nanti)
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
    url = f"https://{AESPORT_DOMAIN}/live-now"
    html = safe_get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
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
    test_url = f"https://{AESPORT_DOMAIN}/upcoming"

    if not get_working_proxy(test_url):
        print("❌ Tidak ada proxy yang bisa dipakai")
        return

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
