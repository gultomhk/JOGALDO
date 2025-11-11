import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
import re
import json
import os
import ssl

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

    print(f"📦 Total slug yang akan diproses: {len(results)}")
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
                        # Validasi: hanya simpan jika ada .m3u8 atau .flv
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

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
    else:
        results = {}

    pending = [s for s in slugs if s not in results or not results[s]]
    print(f"\n🕐 Akan memproses {len(pending)} slug baru...\n")

    async with aiohttp.ClientSession(headers=COMMON_HEADERS) as session:
        for slug in pending:
            s, url = await fetch_stream_url(session, slug)
            if url:  # hanya simpan kalau valid
                results[s] = url
                print(f"💾 Simpan {s}")
            else:
                print(f"⏭️ Lewati {s} (tidak ada stream valid)")

            # Simpan progres setiap iterasi
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n🗺️ Semua selesai. Hasil disimpan ke map6.json ✅")


if __name__ == "__main__":
    asyncio.run(main())
