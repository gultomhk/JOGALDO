import requests
from bs4 import BeautifulSoup
import re
from deep_translator import GoogleTranslator
from pathlib import Path
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====== Load konfigurasi ======
CONFIG_FILE = Path.home() / "keongdata.txt"
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

def clean_value(val):
    return val.strip() if isinstance(val, str) else val

BASE_URL      = clean_value(config_globals.get("BASE_URL"))
TABS          = config_globals.get("TABS", [])
USER_AGENT    = clean_value(config_globals.get("USER_AGENT"))
REFERRER      = clean_value(config_globals.get("REFERRER"))
LOGO_URL      = clean_value(config_globals.get("LOGO_URL"))
MY_WEBSITE    = clean_value(config_globals.get("MY_WEBSITE"))
CF_CLEARANCE  = clean_value(config_globals.get("CF_CLEARANCE"))

# Session dengan bypass Cloudflare
session = requests.Session()
session.verify = False
session.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": REFERRER,
    "Accept": "text/html,application/xhtml+xml;q=0.9",
})
session.cookies.set("cf_clearance", CF_CLEARANCE)

translator = GoogleTranslator(source="vi", target="en")

# ====== Ambil halaman utama ======
print("🌐 Mengambil halaman utama (dengan bypass Cloudflare)...")
resp = session.get(BASE_URL, timeout=15)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

# ====== Fungsi bantu ======
def parse_time_from_slug(slug: str):
    m = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if m:
        h, mm, d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{mm}"
    return "??/??-??.??"

def parse_title_from_slug(slug: str):
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    try:
        translated = translator.translate(title_part)
        return f"{title_part} ({translated})"
    except Exception:
        return title_part

# ====== Mulai proses tab ======
output_lines = ["#EXTM3U"]
seen_slugs = set()

for tab_id in TABS:
    tab_section = soup.select_one(f"#{tab_id}")
    if not tab_section:
        print(f"⚠️ Tab '{tab_id}' tidak ditemukan.")
        continue

    print(f"✅ Memproses tab '{tab_id}' ...")

    for a in tab_section.select("a[href*='/truc-tiep/']"):
        href = a.get("href")
        if not href:
            continue

        slug = href.strip("/")

        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        match_time = parse_time_from_slug(slug)
        title = parse_title_from_slug(slug)

        # Pastikan tidak dobel ?slug=
        if "?slug=" in MY_WEBSITE:
            final_url = f"{MY_WEBSITE}{slug}"
        else:
            final_url = f"{MY_WEBSITE}?slug={slug}"

        output_lines.append(
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title}'
        )
        output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
        output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
        output_lines.append(final_url)

# ====== Simpan ke file ======
filename = "Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"\n✅ File M3U berhasil disimpan: {filename}")
