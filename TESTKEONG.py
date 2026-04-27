import requests
from bs4 import BeautifulSoup
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
import urllib3

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

# ====== SESSION ======
session = requests.Session()
session.verify = False
session.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": REFERRER,
    "Accept": "text/html,application/xhtml+xml;q=0.9",
})
session.cookies.set("cf_clearance", CF_CLEARANCE)

# ====== PROXY GET (opsional tapi aman) ======
def proxied_get(url):
    return session.get(url, timeout=10)

# ====== TRANSLATE FUNCTION (PUNYAMU - FIXED) ======
def translate(text):
    if not text:
        return text
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=vi&tl=en&dt=t&q={quote(text)}"
        )
        data = proxied_get(url).json()
        return data[0][0][0]
    except:
        return text

# ====== MAIN PAGE ======
print("🌐 Mengambil halaman utama...")
resp = session.get(BASE_URL, timeout=15)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

# ====== HELPERS ======
def extract_slug(url):
    if url.startswith("http"):
        return urlparse(url).path.lstrip("/")
    return url.lstrip("/")

def parse_time_from_slug(slug: str):
    m = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if m:
        h, mm, d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{mm}"
    return "??/??-??.??"

def clean_text(text):
    text = text.replace(",", "")
    text = text.replace(":", "")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def clean_parentheses(text: str):
    def repl(m):
        inner = clean_text(m.group(1))
        return f"({inner})"
    return re.sub(r"\((.*?)\)", repl, text)

def parse_title_from_slug(slug: str):
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    title_part = clean_text(title_part)

    # ===== TRANSLATE =====
    translated = translate(title_part)

    # hindari hasil aneh (kadang sama persis)
    if translated and translated.lower() != title_part.lower():
        translated = clean_text(translated)
        full_title = f"{title_part} ({translated})"
    else:
        full_title = title_part

    full_title = clean_parentheses(full_title)
    return full_title

# ====== PROCESS ======
output_lines = ["#EXTM3U"]
seen_full_slugs = set()

for tab_id in TABS:
    tab_section = soup.select_one(f"#{tab_id}")
    if not tab_section:
        print(f"⚠️ Tab '{tab_id}' tidak ditemukan.")
        continue

    print(f"✅ Tab '{tab_id}'")

    for a in tab_section.select("a[href*='/truc-tiep/']"):
        href_main = a.get("href")
        if not href_main:
            continue

        full_main_url = urljoin(BASE_URL, href_main)

        try:
            page = session.get(full_main_url, timeout=15)
            page.raise_for_status()
        except Exception as e:
            print(f"❌ Gagal: {e}")
            continue

        detail = BeautifulSoup(page.text, "html.parser")
        tv_links = detail.select("div#tv_links a.player-link") or [{"href": href_main}]

        print(f"🎬 {len(tv_links)} player")

        for idx, pl in enumerate(tv_links):
            href_player = pl["href"] if isinstance(pl, dict) else pl.get("href")
            if not href_player:
                continue

            slug_full = extract_slug(href_player)

            if slug_full in seen_full_slugs:
                continue
            seen_full_slugs.add(slug_full)

            match_time = parse_time_from_slug(slug_full)
            title = parse_title_from_slug(slug_full)

            if "?slug=" in MY_WEBSITE:
                final_url = f"{MY_WEBSITE}{slug_full}"
            else:
                final_url = f"{MY_WEBSITE}?slug={slug_full}"

            label = (pl.get_text(strip=True) if not isinstance(pl, dict) else "") or f"Server {idx+1}"

            output_lines.append(
                f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}",{match_time} {title} [{label}]'
            )
            output_lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
            output_lines.append(f"#EXTVLCOPT:http-referrer={REFERRER}")
            output_lines.append(final_url)

# ====== SAVE ======
filename = "Keongphut_sport.m3u"
with open(filename, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"\n✅ Selesai: {filename}")
