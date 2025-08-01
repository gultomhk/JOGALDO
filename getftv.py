from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import requests
import urllib.parse
import re

# ====== Konfigurasi ======
BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

def extract_m3u8_urls(html):
    """Ekstrak URL m3u8 dari HTML dengan berbagai metode"""
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

# ========= Ambil daftar slug =========
def extract_slug(row):
    """Ekstrak slug dari elemen baris HTML."""
    # Coba dari atribut onclick dulu
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    
    # Fallback ke <a href="/match/...">
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    
    return None

def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            # Ambil timestamp dan filter jika lebih dari threshold jam yang lalu
            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))

                if event_time_local < (now - timedelta(hours=hours_threshold)):
                    continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

# Cek dan load config
if not BODATTVDATA_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {BODATTVDATA_FILE}")

config = load_config(BODATTVDATA_FILE)

# Validasi isi config
required_keys = ["DEFAULT_URL", "BASE_URL", "WORKER_URL", "LOGO", "USER_AGENT"]
missing = [key for key in required_keys if key not in config]
if missing:
    raise ValueError(f"❌ Missing config keys: {', '.join(missing)}")

# Baru di sini HEADERS boleh didefinisikan
HEADERS = {
    "User-Agent": config["USER_AGENT"],
    "Referer": config["BASE_URL"] + "/"
}

now = datetime.now(tz.gettz("Asia/Jakarta"))

def clean_title(title):
    title = title.replace("football", "")
    title = re.sub(r"\s*[:|•]\s*", " ", title)
    title = re.sub(r",\s*", " ", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -")

def extract_matches_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U"]
    seen = set()

    matches_table = soup.select("div.common-table-row.table-row")
    print(f"⛵️ Found {len(matches_table)} table-row matches")

    for row in matches_table:
        try:
            slug = None
            link = row.select_one("a[href^='/match/']")
            if link:
                slug = link['href'].replace('/match/', '').strip()
            elif row.has_attr("onclick"):
                match = re.search(r"/match/([^']+)", row["onclick"])
                if match:
                    slug = match.group(1).strip()

            if not slug or slug in seen:
                continue
            seen.add(slug)

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                waktu = event_time_local.strftime("%d/%m-%H.%M")
            else:
                waktu = "00/00-00.00"
                event_time_local = now

            slug_lower = slug.lower()
            is_exception = any(kw in slug_lower for kw in ["tennis", "billiards", "snooker", "worldssp", "superbike"])
            if not is_exception and event_time_local < (now - timedelta(hours=2)):
                continue

            wrapper = row.select_one(".list-club-wrapper")
            if wrapper:
                name_tags = wrapper.select(".club-name")
                texts = [t.text.strip() for t in name_tags if t.text.strip().lower() != "vs"]
                if len(texts) >= 2:
                    title = f"{texts[0]} vs {texts[1]}"
                elif len(texts) == 1:
                    title = texts[0]
                else:
                    title = wrapper.get_text(separator=" ", strip=True)
            else:
                title = clean_title(slug.replace("-", " "))

            title = clean_title(title)
            if title.lower() == "vs" or len(title.strip()) < 3:
                print(f"⚠️  Skip bad title (table): {title}")
                continue

            print(f"📃 Parsed: {waktu} | {title}")

            # Ambil HTML detail halaman pertandingan
            detail_url = f"{BASE_URL}/match/{slug}"
            try:
                resp = requests.get(detail_url, headers=HEADERS, timeout=10)
                m3u8_urls = extract_m3u8_urls(resp.text)
            except Exception as e:
                print(f"⚠️  Gagal fetch detail untuk {slug}: {e}")
                m3u8_urls = []

            if not m3u8_urls:
                # Tetap masukkan entri jika tidak ada server ditemukan
                display_name = f"{waktu} {title}"
                url = f"{WORKER_URL}{slug}"
                output += [
                    f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{display_name}',
                    f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                    f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                    url
                ]
            else:
                for i, real_url in enumerate(m3u8_urls):
                    suffix = f"server{i+1}" if i > 0 else ""
                    display_name = f"{waktu} {title} {suffix}".strip()
                    slug_full = f"{slug} {suffix}".strip()
                    url = f"{WORKER_URL}{slug}/{suffix}" if suffix else f"{WORKER_URL}{slug}"
                    output += [
                        f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{display_name}',
                        f'#EXTVLCOPT:http-user-agent={USER_AGENT}',
                        f'#EXTVLCOPT:http-referrer={BASE_URL}/',
                        url
                    ]

        except Exception as e:
            print(f"❌ Error parsing table row: {e}")
            continue

    return "\n".join(output)
    
if __name__ == "__main__":
    with open("BODATTV_PAGE_SOURCE.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = extract_matches_from_html(html)

    with open("bodattv_live.m3u", "w", encoding="utf-8") as f:
        f.write(result)

    print("\n✅ File bodattv_live.m3u berhasil dibuat dengan format worker URL yang konsisten")
