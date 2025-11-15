import requests
import json
import re
from pathlib import Path

# ==========================
# KONFIGURASI
# ==========================
cvvpdata_FILE = Path.home() / "cvvpdata_file.txt"
config_vars = {}

with open(cvvpdata_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

PPV_API_URL = config_vars.get("PPV_API_URL")
RESOLVER_API = config_vars.get("RESOLVER_API")  # contoh: http://localhost:7860/multi

OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

# ============================================================
# Ambil semua iframe dari PPV API
# ============================================================
def get_all_iframes():
    """Ambil semua iframe dari PPV API"""
    print("📺 Mengambil event dari PPV.to...")

    r = requests.get(PPV_API_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()

    results = []
    data = r.json()

    for cat in data.get("streams", []):
        for stream in cat.get("streams", []):
            iframe = stream.get("iframe")
            if iframe:
                results.append(iframe)

    print(f"✅ Total iframe ditemukan: {len(results)}")
    return results


# ============================================================
# Resolver multi-embed
# ============================================================
def resolve_multi(iframes):
    """Kirim semua iframe ke Playwright resolver 1 kali"""
    print("🚀 Mengirim ke resolver multi-embed...")

    params = [("u", u) for u in iframes]

    r = requests.get(RESOLVER_API, params=params, headers=HEADERS, timeout=200)

    # Kalau server kasih error 400, tampilkan text asli
    if r.status_code != 200:
        print("🔥 SERVER ERROR:", r.text)
        r.raise_for_status()

    print("🎯 Resolver selesai.")
    return r.json()


# ============================================================
# Simpan JSON
# ============================================================
def save_json(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 map8.json berhasil dibuat → {OUTPUT_FILE.absolute()}")


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    iframes = get_all_iframes()
    results = resolve_multi(iframes)
    save_json(results)
