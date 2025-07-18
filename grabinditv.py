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
proxy_list_url = config.get("proxy_list_url")  # opsional

# === Fungsi ambil list proxy ===
def get_proxy_list(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.text.strip().splitlines()
    except Exception as e:
        print(f"[!] Gagal ambil proxy list: {e}", file=sys.stderr)
        return []

# === Fungsi coba request dengan 1 proxy ===
def try_proxy(api_url, proxy, headers):
    proxies = {"http": proxy, "https": proxy}
    try:
        print(f"[•] Mencoba proxy: {proxy}", file=sys.stderr)
        res = requests.get(api_url, headers=headers, proxies=proxies, timeout=10)
        res.raise_for_status()
        return res.text
    except Exception as e:
        print(f"[×] Proxy gagal: {proxy} → {e}", file=sys.stderr)
        return None

# === Ambil URL MPD ===
def get_mpd_url(channel_id):
    url = url_template.format(channel_id=channel_id)
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"⚠️ Gagal langsung: {channel_id} → {e}", file=sys.stderr)
        if proxy_list_url:
            proxy_list = get_proxy_list(proxy_list_url)
            for proxy in proxy_list:
                html = try_proxy(url, proxy, headers)
                if html:
                    break
            else:
                print(f"❌ Semua proxy gagal untuk {channel_id}", file=sys.stderr)
                return None
        else:
            return None

    mpd = re.search(r"var\s+v\d+\s*=\s*'(https://[^']+\.mpd[^']*)'", html)
    return mpd.group(1) if mpd else None

# === Proses semua channel ===
result_map = {}
for cid in channel_ids:
    mpd_url = get_mpd_url(cid)
    if mpd_url:
        result_map[cid] = mpd_url
        print(f"✅ {cid}: {mpd_url}")
    else:
        print(f"⚠️  {cid}: MPD not found")

# === Simpan hasil ke file ===
with open("map3.json", "w", encoding="utf-8") as f:
    json.dump(result_map, f, indent=2, ensure_ascii=False)

print("\n📁 map3.json berhasil dibuat.")
