import requests
import re
import json
import sys
from pathlib import Path

# === Path ke file konfigurasi ===
INDIDATA_FILE = Path.home() / "indidata_file.txt"

# === Muat konfigurasi dari file ===
config = {}
exec(INDIDATA_FILE.read_text(encoding="utf-8"), config)

headers = config["headers"]
channel_ids = config["channel_ids"]
url_template = config["url_template"]
proxy_list_url = config.get("proxy_list_url")

# === Ambil list proxy dari URL ===
def get_proxy_list(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.text.strip().splitlines()
    except Exception as e:
        print(f"[!] Gagal ambil proxy list: {e}", file=sys.stderr)
        return []

# === Fetch HTML (tanpa atau dengan proxy) ===
def fetch_html(url):
    # Coba langsung dulu
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return res.text
    except:
        pass

    # Coba lewat proxy satu per satu
    for proxy in proxy_list:
        print(f"🔁 Mencoba proxy: {proxy}")
        proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
        try:
            res = requests.get(url, headers=headers, proxies=proxies, timeout=10)
            res.raise_for_status()
            return res.text
        except Exception:
            print(f"[×] Proxy gagal: {proxy}")
            continue

    return None

# === Cari MPD URL dari satu channel ===
def get_mpd_url(channel_id):
    url = url_template.format(channel_id=channel_id)
    html = fetch_html(url)
    if not html:
        return None
    match = re.search(r"var\s+v\d+\s*=\s*'(https://[^']+\.mpd[^']*)'", html)
    return match.group(1) if match else None

# === Ambil proxy list dulu ===
proxy_list = get_proxy_list(proxy_list_url)

# === Proses semua channel ===
result = {}
for cid in channel_ids:
    mpd = get_mpd_url(cid)
    if mpd:
        result[cid] = mpd
        print(f"✅ {cid}: {mpd}")
    else:
        print(f"⚠️  {cid}: MPD not found or no title")

# === Simpan ke map3.json ===
with open("map3.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("\n📁 map3.json berhasil dibuat.")
