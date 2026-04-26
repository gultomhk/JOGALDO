import requests
from bs4 import BeautifulSoup
import re
from deep_translator import GoogleTranslator
from pathlib import Path
from urllib.parse import urljoin, urlparse
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
def extract_slug(url):

    if url.startswith("http://") or url.startswith("https://"):
        parsed = urlparse(url)
        return parsed.path.lstrip("/")
    return url.lstrip("/")

def parse_time_from_slug(slug: str):
    m = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if m:
        h, mm, d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{mm}"
    return "??/??-??.??"


def clean_parentheses(text: str):
    def repl(m):
        inner = m.group(1)
        inner = inner.replace(",", "")                # ❌ hapus koma
        inner = inner.replace(":", "")                # ❌ hapus titik dua sekalian
        inner = re.sub(r"\s{2,}", " ", inner)         # rapikan spasi
        return f"({inner.strip()})"
    return re.sub(r"\((.*?)\)", repl, text)


def parse_title_from_slug(slug: str):
    # =========================
    # BASE TITLE
    # =========================
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()

    # rapikan spasi awal
    title_part = re.sub(r"\s{2,}", " ", title_part)

    try:
        translated = translator.translate(title_part)

        # 🔥 CLEAN TRANSLATION
        translated = translated.replace(",", "")
        translated = translated.replace(":", "")
        translated = re.sub(r"\s{2,}", " ", translated).strip()

        full_title = f"{title_part} ({translated})"

    except Exception:
        full_title = title_part

    # 🔥 FINAL CLEAN (antisipasi semua kasus)
    full_title = clean_parentheses(full_title)
    full_title = re.sub(r"\s{3,}", "  ", full_title).strip()

    return full_title


# ====== Mulai proses tab ======
output_lines = ["#EXTM3U"]
seen_full_slugs = set()

for tab_id in TABS:
    tab_section = soup.select_one(f"#{tab_id}")
    if not tab_section:
        print(f"⚠️ Tab '{tab_id}' tidak ditemukan.")
        continue

    print(f"✅ Memproses tab '{tab_id}' ...")

    for a in tab_section.select("a[href*='/truc-tiep/']"):
        href_main = a.get("href")
        if not href_main:
            continue

        full_main_url = urljoin(BASE_URL, href_main)
        slug_main = extract_slug(href_main)

        try:
            page = session.get(full_main_url, timeout=15)
            page.raise_for_status()
        except Exception as e:
            print(f"❌ Gagal load halaman {full_main_url}: {e}")
            continue

        detail = BeautifulSoup(page.text, "html.parser")

        tv_links = detail.select("div#tv_links a.player-link")
        if not tv_links:
            tv_links = [{"href": href_main}]

        print(f"🎬 Ditemukan {len(tv_links)} player pada {full_main_url}")

        for idx, pl in enumerate(tv_links):
            href_player = pl["href"] if isinstance(pl, dict) else pl.get("href")
            if not href_player:
                continue

            slug_full = extract_slug(href_player)

            if slug_full in seen_full_slugs:
                continue
            seen_full_slugs.add(slug_full)

            # =========================
            # PARSE
            # =========================
            match_time = parse_time_from_slug(slug_full)
            title = parse_title_from_slug(slug_full)

            # =========================
            # URL Worker
            # =========================
            if "?slug=" in MY_WEBSITE:
                final_url = f"{MY_WEBSITE}{slug_full}"
            else:
                final_url = f"{MY_WEBSITE}?slug={slug_full}"

            label = (pl.get_text(strip=True) if not isinstance(pl, dict) else "") or f"Server {idx+1}"

            # =========================
            # OUTPUT
            # =========================
            output_lines.append(
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title} [{label}]'
            )
            output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
            output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
            output_lines.append(final_url)

# ====== Simpan ke file ======
filename = "Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"\n✅ File M3U berhasil disimpan: {filename}")
