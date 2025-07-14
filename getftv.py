from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import requests
import re

# ====== Konfigurasi ======
BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

# Load konfigurasi dari file
def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

# Ambil URL .m3u8 dari halaman slug
def get_m3u8_from_slug(slug, user_agent):
    try:
        target_url = f"https://fstv.online/match/{slug}"
        headers = {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(target_url, headers=headers, timeout=10)

        tree = BeautifulSoup(resp.text, "lxml")
        iframe = tree.select_one("iframe[src]")
        if not iframe:
            return None

        iframe_url = urljoin("https://fstv.online", iframe["src"])
        parsed = urlparse(iframe_url)
        link_encoded = parse_qs(parsed.query).get("link", [None])[0]
        return unquote(link_encoded) if link_encoded else None

    except Exception as e:
        print(f"❌ Error fetch {slug}: {e}")
        return None

# Pembersih judul
def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|\u2022]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

# Ekstrak pertandingan dari HTML
def extract_matches_from_html(html, config):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()
    now = datetime.now(tz.gettz("Asia/Jakarta"))

    def format_entry(slug, waktu, title):
        m3u8 = get_m3u8_from_slug(slug, config["USER_AGENT"])
        if not m3u8:
            print(f"⚠️  Gagal ambil M3U8: {slug}")
            return []
        return [
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{config["LOGO"]}",{waktu} {title}',
            f'#EXTVLCOPT:http-user-agent={config["USER_AGENT"]}',
            f'#EXTVLCOPT:http-referrer={config["BASE_URL"]}/',
            m3u8
        ]

    # === Slide item (utama) ===
    for match in soup.select("div.slide-item"):
        a_tag = match.select_one('a.btn-club[href]')
        if not a_tag:
            continue
        slug = a_tag['href'].replace('/match/', '').strip()
        if slug in seen:
            continue
        seen.add(slug)

        ts_tag = match.select_one('.timestamp')
        ts_value = ts_tag.get('data-timestamp') if ts_tag else None
        event_time = datetime.fromtimestamp(int(ts_value), tz=timezone.utc).astimezone(tz.gettz("Asia/Jakarta")) if ts_value else now
        if event_time < (now - timedelta(hours=2)):
            continue

        waktu = event_time.strftime("%d/%m-%H.%M")
        teams = match.select('.club-name')
        title = clean_title(f"{teams[0].text.strip()} vs {teams[1].text.strip()}" if len(teams) >= 2 else slug.replace("-", " "))
        if len(title) < 3:
            continue

        print(f"📃 {waktu} | {title}")
        output += format_entry(slug, waktu, title)

    # === Table row (lain-lain) ===
    for row in soup.select("div.common-table-row.table-row"):
        link = row.select_one("a[href^='/match/']")
        if not link:
            continue
        slug = link['href'].replace('/match/', '').strip()
        if slug in seen:
            continue
        seen.add(slug)

        waktu_tag = row.select_one(".match-time")
        ts_value = int(waktu_tag['data-timestamp']) if waktu_tag and waktu_tag.has_attr('data-timestamp') else None
        event_time = datetime.fromtimestamp(ts_value, tz=timezone.utc).astimezone(tz.gettz("Asia/Jakarta")) if ts_value else now
        waktu = event_time.strftime("%d/%m-%H.%M")

        if event_time < (now - timedelta(hours=2)):
            continue

        wrapper = row.select_one(".list-club-wrapper")
        title_tags = wrapper.select(".club-name") if wrapper else []
        title = clean_title(f"{title_tags[0].text.strip()} vs {title_tags[1].text.strip()}" if len(title_tags) >= 2 else slug.replace("-", " "))
        if len(title) < 3:
            continue

        print(f"📃 {waktu} | {title}")
        output += format_entry(slug, waktu, title)

    return "\n".join(output)

# ===== Eksekusi utama =====
if __name__ == "__main__":
    if not BODATTVDATA_FILE.exists():
        raise FileNotFoundError(f"❌ File config tidak ditemukan: {BODATTVDATA_FILE}")

    config = load_config(BODATTVDATA_FILE)
    required_keys = ["DEFAULT_URL", "BASE_URL", "WORKER_URL", "LOGO", "USER_AGENT"]
    if missing := [k for k in required_keys if k not in config]:
        raise ValueError(f"❌ Missing config keys: {', '.join(missing)}")

    resp = requests.get(config["DEFAULT_URL"], headers={"User-Agent": config["USER_AGENT"]})
    m3u_output = extract_matches_from_html(resp.text, config)

    with open("bodattv_live.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_output)

    print("\n✅ File bodattv_live.m3u berhasil dibuat.")
