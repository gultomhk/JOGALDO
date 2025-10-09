from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import urllib.parse
import requests
import re

# ====== Konfigurasi ======
BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

def extract_m3u8_urls(html):
    """Ekstrak URL .m3u8 dari elemen dengan atribut data-link"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if raw.endswith(".m3u8") and raw.startswith("http"):
            print(f"   🔗 Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)
        elif "/player?link=" in raw:
            decoded = urllib.parse.unquote(raw)
            if decoded.endswith(".m3u8") and decoded.startswith("http"):
                print(f"   🔗 Dari iframe: ✅ {decoded}")
                m3u8_urls.append(decoded)
            else:
                print(f"   ⚠️ Iframe tapi bukan m3u8: {raw}")
        else:
            print(f"   ⚠️ Skip: {raw}")
    return m3u8_urls

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
required_keys = ["DEFAULT_URL", "BASE_URL", "WORKER_URL", "LOGO", "USER_AGENT"]
missing = [key for key in required_keys if key not in config]
if missing:
    raise ValueError(f"❌ Missing config keys: {', '.join(missing)}")

BASE_URL = config["BASE_URL"]
WORKER_URL = config["WORKER_URL"]
LOGO = config["LOGO"]
USER_AGENT = config["USER_AGENT"]

now = datetime.now(tz.gettz("Asia/Jakarta"))

def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def get_slug_page(slug):
    try:
        url = f"{BASE_URL}/match/{slug}"
        headers = {"User-Agent": USER_AGENT, "Referer": BASE_URL}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"❌ Gagal ambil halaman slug {slug}: {e}")
        return ""

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    # Ambil semua match item (2 kemungkinan struktur)
    matches = soup.select("div.common-table-row.table-row, div.slide-item")
    print(f"⛵️ Found {len(matches)} match items")

    for item in matches:
        try:
            # --- slug / link ---
            link_tag = item.select_one("a[href^='/match/']")
            slug = None
            if link_tag:
                slug = link_tag['href'].replace('/match/', '').strip()
            if not slug:
                continue
            if slug in seen:
                continue
            seen.add(slug)

            # --- waktu ---
            ts_tag = item.select_one(".timestamp[data-timestamp]")
            if ts_tag:
                try:
                    timestamp = int(ts_tag["data-timestamp"])
                    event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                    waktu = event_time_local.strftime("%d/%m-%H.%M")
                except:
                    waktu = "00/00-00.00"
                    event_time_local = now
            else:
                waktu = "00/00-00.00"
                event_time_local = now

            # --- nama liga ---
            league_tag = item.select_one(".match-name")
            league = clean_title(league_tag.get_text(strip=True)) if league_tag else "Unknown League"

            # --- nama tim ---
            clubs = [c.get_text(strip=True) for c in item.select(".club-name")]
            if len(clubs) >= 2:
                title = f"{clubs[0]} vs {clubs[1]}"
            else:
                title = slug.replace("-", " ")

            title = clean_title(title)
            if not title or len(title) < 3:
                continue

            print(f"📃 Parsed: {waktu} | {league} | {title}")

            # --- ambil halaman slug ---
            slug_html = get_slug_page(slug)
            m3u8_urls = extract_m3u8_urls(slug_html)

            if not m3u8_urls:
                print(f"⚠️ Tidak ada server untuk {slug}, skip")
                continue

            # --- buat entri M3U ---
            full_title = f"{league} - {title}"
            output += [
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{waktu} {full_title}',
                f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                f'{WORKER_URL}{slug}'
            ]

        except Exception as e:
            print(f"❌ Error parsing match: {e}")
            continue

    return "\n".join(output)

if __name__ == "__main__":
    with open("BODATTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = extract_matches_from_html(html)

    with open("bodattv_live.m3u", "w", encoding="utf-8") as f:
        f.write(result)

    print("\n✅ File bodattv_live.m3u berhasil dibuat dengan format worker URL yang konsisten")
