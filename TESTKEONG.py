import requests
from bs4 import BeautifulSoup
import re
from deep_translator import GoogleTranslator
from datetime import datetime
from pathlib import Path


# Path ke file config
CONFIG_FILE = Path.home() / "keongdata.txt"

# --- Load konfigurasi dari file ---
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

# Assign variabel dari config
BASE_URL = config_globals.get("BASE_URL")
TABS = config_globals.get("TABS")
USER_AGENT = config_globals.get("USER_AGENT")
REFERRER = config_globals.get("REFERRER")
LOGO_URL = config_globals.get("LOGO_URL")
MY_WEBSITE = config_globals.get("MY_WEBSITE")



headers = {"User-Agent": USER_AGENT}

# ====== Ambil halaman utama ======
print("🌐 Mengambil halaman utama...")
resp = requests.get(BASE_URL, headers=headers)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

translator = GoogleTranslator(source="vi", target="en")


def parse_time_from_slug(slug: str):
    """Ambil waktu & tanggal dari slug."""
    match = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if match:
        h, m, d, mo, y = match.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{m}"
    return "??/??-??.??"


def parse_title_from_slug(slug: str):
    """Ambil nama pertandingan dari slug dan terjemahkan ke English."""
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()

    try:
        translated = translator.translate(title_part)
        combined = f"{title_part} ({translated})"
    except Exception as e:
        print(f"⚠️ Gagal translate '{title_part}': {e}")
        combined = title_part

    return combined


# ====== Proses tiap tab ======
output_lines = ["#EXTM3U"]
seen_slugs = set()  # ← untuk hindari duplikasi

for tab_id in TABS:
    tab_section = soup.select_one(f"#{tab_id}")
    if not tab_section:
        print(f"⚠️ Tab '{tab_id}' tidak ditemukan di halaman.")
        continue

    print(f"✅ Tab '{tab_id}' ditemukan, memproses...")

    for a in tab_section.select("a[href*='/truc-tiep/']"):
        href = a.get("href")
        if not href:
            continue

        # Normalisasi slug
        slug = re.sub(r"^/|/$", "", href)
        if slug in seen_slugs:
            continue  # skip duplikat
        seen_slugs.add(slug)

        match_time = parse_time_from_slug(slug)
        title = parse_title_from_slug(slug)
        full_slug_url = f"{MY_WEBSITE}{slug}/"

        output_lines.append(
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title}'
        )
        output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
        output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
        output_lines.append(full_slug_url)

# ====== Simpan ke file ======
filename = f"Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print(f"\n✅ File M3U berhasil disimpan: {filename}")
