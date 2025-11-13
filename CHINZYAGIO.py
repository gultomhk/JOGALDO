import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
import re
import json
import os
import ssl
from pathlib import Path
from datetime import datetime

# ==========================
# KONFIGURASI
# ==========================
CHINZYAIGODATA_FILE = Path.home() / "chinzyaigodata_file.txt"
config_vars = {}
with open(CHINZYAIGODATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL")
API_URL = config_vars.get("API_URL")

OUTPUT_FILE = "map6.json"
TABS = ["football", "basketball", "volleyball", "badminton", "tennis"]

COMMON_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "id,en-US;q=0.9,en;q=0.8,vi;q=0.7",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}

sslcontext = ssl.create_default_context()
sslcontext.check_hostname = False
sslcontext.verify_mode = ssl.CERT_NONE


# ====== Fungsi bantu ======
def parse_time_from_slug(slug: str):
    match = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if match:
        h, m, d, mo, y = match.groups()
        return f"{int(d):02d}/{int(mo):02d}-{int(h):02d}.{m}"
    return "??/??-??.??"


def parse_datetime_key(slug: str):
    match = re.search(r"luc-(\d{1,2})(\d{2})-ngay-(\d{1,2})-(\d{1,2})-(\d{4})", slug)
    if match:
        h, m, d, mo, y = map(int, match.groups())
        try:
            return datetime(y, mo, d, h, m)
        except ValueError:
            return datetime.min
    return datetime.min


def parse_title_from_slug(slug: str):
    title_part = re.sub(r"^truc-tiep[-/]*", "", slug)
    title_part = re.sub(r"-luc-\d{3,4}-ngay-\d{1,2}-\d{1,2}-\d{4}$", "", title_part)
    title_part = re.sub(r"[-_/]+", " ", title_part).strip()
    return title_part


# ==========================
# Ambil semua slug dari homepage
# ==========================
def get_all_slugs():
    print("🌐 Mengambil halaman utama untuk parse semua slug...")
    resp = requests.get(BASE_URL, headers=COMMON_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for tab in TABS:
        tab_section = soup.select_one(f"#{tab}")
        if not tab_section:
            continue
        found = []
        for a in tab_section.select("a[href*='/truc-tiep/']"):
            href = a.get("href", "")
            if not href:
                continue
            slug = re.sub(r"^/|/$", "", href)
            if slug not in found:
                found.append(slug)
        print(f"✅ {tab}: ditemukan {len(found)} slug")
        results.extend(found)

    # Urutkan berdasarkan waktu terbaru
    results = sorted(results, key=parse_datetime_key, reverse=True)

    print(f"📦 Total slug yang akan diproses (urut waktu): {len(results)}")
    return results


# ==========================
# Ambil URL stream dari API Hugging Face (302 redirect)
# ==========================
async def fetch_stream_url(session, slug, retries=3):
    url = API_URL.format(slug)
    for attempt in range(1, retries + 1):
        try:
            async with session.get(url, allow_redirects=False, ssl=sslcontext, timeout=25) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    stream_url = resp.headers.get("Location", "")
                    if stream_url:
                        if re.search(r"\.(m3u8|flv)\b", stream_url):
                            print(f"🎯 {slug} → {stream_url}")
                            return slug, stream_url
                        else:
                            print(f"⏭️ Skip {slug}: redirect bukan .m3u8/.flv ({stream_url})")
                            return slug, ""
                    else:
                        print(f"⚠️ Tidak ada header Location untuk {slug}")
                else:
                    print(f"⚠️ {slug} gagal, status {resp.status}")
        except Exception as e:
            print(f"❌ Percobaan {attempt}/{retries} gagal untuk {slug}: {e}")
            await asyncio.sleep(1)
    return slug, ""


# ==========================
# MAIN
# ==========================
async def main():
    slugs = get_all_slugs()
    print(f"\n🕐 Mulai proses {len(slugs)} slug...\n")

    new_results = {}

    async with aiohttp.ClientSession(headers=COMMON_HEADERS) as session:
        for slug in slugs:
            s, url = await fetch_stream_url(session, slug)
            if url:
                new_results[s] = url
                time_str = parse_time_from_slug(s)
                title = parse_title_from_slug(s)
                print(f"💾 [{time_str}] {title}")
            else:
                print(f"⏭️ Lewati {s} (tidak ada stream valid)")

    # Rewrite total map6.json hanya jika sukses run
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_results, f, indent=2, ensure_ascii=False)

    print("\n✅ map6.json berhasil di-rewrite total setelah sukses run.")


if __name__ == "__main__":
    asyncio.run(main())
