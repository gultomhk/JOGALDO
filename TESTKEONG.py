import requests
from bs4 import BeautifulSoup
import re
from deep_translator import GoogleTranslator
from datetime import datetime
from pathlib import Path

# ====== Load konfigurasi ======
CONFIG_FILE = Path.home() / "keongdata.txt"
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

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
    # Hapus prefix "truc-tiep/" dan suffix waktu
    title_part = re.sub(r"^truc-tiep/", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    
    # Pisahkan tim vs tim
    if " vs " in title_part.lower():
        teams = title_part.split(" vs ")
        if len(teams) == 2:
            team1, team2 = teams[0].strip(), teams[1].strip()
            try:
                team1_en = translator.translate(team1)
                team2_en = translator.translate(team2)
                combined = f"{team1} vs {team2} ({team1_en} vs {team2_en})"
            except Exception as e:
                print(f"⚠️ Gagal translate '{title_part}': {e}")
                combined = f"{team1} vs {team2}"
        else:
            combined = title_part
    else:
        try:
            translated = translator.translate(title_part)
            combined = f"{title_part} ({translated})"
        except Exception as e:
            print(f"⚠️ Gagal translate '{title_part}': {e}")
            combined = title_part

    return combined


def normalize_slug_url(slug: str):
    """Normalisasi URL slug untuk format yang konsisten."""
    # Hapus awalan dan akhiran slash
    slug = slug.strip('/')
    
    # Pastikan format URL konsisten
    if not slug.startswith('truc-tiep/'):
        slug = f"truc-tiep/{slug}"
    
    # Pastikan URL berakhir dengan slash
    if not slug.endswith('/'):
        slug = f"{slug}/"
    
    return slug


# ====== Proses tiap tab ======
output_lines = ["#EXTM3U"]
seen_slugs = set()

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
        slug = href.strip('/')
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        # Normalisasi URL untuk format yang konsisten
        normalized_slug = normalize_slug_url(slug)
        
        match_time = parse_time_from_slug(normalized_slug)
        title = parse_title_from_slug(normalized_slug)
        
        # Format URL final - gunakan format dengan query parameter
        full_slug_url = f"{MY_WEBSITE}file.php?slug={normalized_slug.rstrip('/')}"

        output_lines.append(
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title}'
        )
        output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
        output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
        output_lines.append(full_slug_url)
        output_lines.append("")  # Baris kosong antar channel

# ====== Simpan ke file ======
filename = f"Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print(f"\n✅ File M3U berhasil disimpan: {filename}")
print(f"📊 Total channel: {len(seen_slugs)}")
