import requests
import re
import json
from pathlib import Path

# Path ke file konfigurasi
INDIDATA_FILE = Path.home() / "indidata_file.txt"

# Muat konfigurasi dari file
config = {}
exec(INDIDATA_FILE.read_text(encoding="utf-8"), config)

headers = config["headers"]
channel_ids = config["channel_ids"]
url_template = config["url_template"]

def get_mpd_url(channel_id):
    try:
        url = url_template.format(channel_id=channel_id)
        res = requests.get(url, headers=headers, timeout=10)
        html = res.text
        mpd = re.search(r"var\s+v\d+\s*=\s*'(https://[^']+\.mpd[^']*)'", html)
        if not mpd:
            # Simpan HTML ke file debug jika MPD tidak ditemukan
            with open(f"debug_{channel_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        return mpd.group(1) if mpd else None
    except Exception as e:
        print(f"❌ Error: {channel_id} -> {e}")
        return None

# Proses semua channel
result_map = {}
for cid in channel_ids:
    mpd_url = get_mpd_url(cid)
    if mpd_url:
        result_map[cid] = mpd_url
        print(f"✅ {cid}: {mpd_url}")
    else:
        print(f"⚠️  {cid}: MPD not found")

# Simpan hasil ke map3.json
with open("map3.json", "w", encoding="utf-8") as f:
    json.dump(result_map, f, indent=2, ensure_ascii=False)

print("\n📁 map3.json berhasil dibuat.")
