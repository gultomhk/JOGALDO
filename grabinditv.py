import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

# Path ke file konfigurasi
INDIDATA_FILE = Path.home() / "indidata_file.txt"

# Muat konfigurasi dari file
config = {}
exec(INDIDATA_FILE.read_text(encoding="utf-8"), config)

headers = config["headers"]
channel_ids = config["channel_ids"]
url_template = config["url_template"]

def get_mpd_url(channel_id, playwright):
    try:
        url = url_template.format(channel_id=channel_id)
        browser = playwright.chromium.launch()
        context = browser.new_context(extra_http_headers=headers)
        page = context.new_page()
        page.goto(url, timeout=15000)
        html = page.content()
        mpd_match = re.search(r"var\s+v\d+\s*=\s*'(https://[^']+\.mpd[^']*)'", html)
        if not mpd_match:
            with open(f"debug_{channel_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        context.close()
        browser.close()
        return mpd_match.group(1) if mpd_match else None
    except Exception as e:
        print(f"❌ Error {channel_id}: {e}")
        return None

# Jalankan Playwright dan proses semua channel
result_map = {}
with sync_playwright() as p:
    for cid in channel_ids:
        mpd_url = get_mpd_url(cid, p)
        if mpd_url:
            result_map[cid] = mpd_url
            print(f"✅ {cid}: {mpd_url}")
        else:
            print(f"⚠️  {cid}: MPD not found or no title")

# Simpan ke file
with open("map3.json", "w", encoding="utf-8") as f:
    json.dump(result_map, f, indent=2, ensure_ascii=False)

print("📁 map3.json berhasil dibuat.")
