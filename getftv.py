from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import re, requests

# Konfigurasi
BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not BODATTVDATA_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {BODATTVDATA_FILE}")

config = load_config(BODATTVDATA_FILE)
BASE_URL = config["BASE_URL"]
LOGO = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

now = datetime.now(tz.gettz("Asia/Jakarta"))

def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def resolve_m3u8(slug):
    match_url = f"{BASE_URL}/match/{slug}"
    try:
        resp = requests.get(match_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        tree = html.fromstring(resp.text)
        iframe = tree.xpath('//iframe/@src')
        if not iframe:
            return None
        iframe_url = urljoin(BASE_URL, iframe[0])
        parsed = urlparse(iframe_url)
        query = parse_qs(parsed.query)
        m3u8_encoded = query.get("link", [None])[0]
        if m3u8_encoded:
            return unquote(m3u8_encoded)
    except:
        return None

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    matches = soup.select("div.slide-item, div.common-table-row.table-row")
    print(f"🔍 Found {len(matches)} matches")

    for match in matches:
        link = match.select_one("a[href^='/match/']")
        if not link:
            continue
        slug = link['href'].replace('/match/', '').strip()
        if slug in seen:
            continue
        seen.add(slug)

        waktu = "00/00-00.00"
        timestamp_tag = match.select_one("[data-timestamp]")
        if timestamp_tag and timestamp_tag.get("data-timestamp"):
            try:
                ts = int(timestamp_tag["data-timestamp"])
                utc_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                local_time = utc_time.astimezone(tz.gettz("Asia/Jakarta"))
                if local_time < now - timedelta(hours=2):
                    continue
                waktu = local_time.strftime("%d/%m-%H.%M")
            except:
                pass

        title = None
        teams = match.select(".club-name")
        if len(teams) >= 2:
            title = f"{teams[0].text.strip()} vs {teams[1].text.strip()}"
        elif len(teams) == 1:
            title = teams[0].text.strip()
        else:
            title = clean_title(slug.replace("-", " "))
        title = clean_title(title)

        if not title or title.lower() == "vs" or len(title.strip()) < 3:
            continue

        print(f"📺 {waktu} | {title} -> resolving slug: {slug}")
        m3u8_url = resolve_m3u8(slug)
        if not m3u8_url:
            print(f"❌ M3U8 not found for slug: {slug}")
            continue

        output += [
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {title}',
            f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
            f'#EXTVLCOPT:http-referrer={BASE_URL}/',
            m3u8_url
        ]

    return "\n".join(output)

# Main
if __name__ == "__main__":
    with open("BODATTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = extract_matches_from_html(html)

    with open("bodattv_live_final.m3u", "w", encoding="utf-8") as f:
        f.write(result)

    print("✅ File bodattv_live_final.m3u berhasil dibuat.")
