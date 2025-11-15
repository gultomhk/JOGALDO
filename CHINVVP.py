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
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

# ============================================================
# 1. Ambil semua iframe dari API PPV.to
# ============================================================
def get_all_iframes():
    print("📺 Mengambil event dari PPV.to...")
    r = requests.get(PPV_API_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()

    data = r.json()

    results = []
    for cat in data.get("streams", []):
        for stream in cat.get("streams", []):
            iframe = stream.get("iframe")
            # FILTER AGAR CLEAN
            if iframe and isinstance(iframe, str) and iframe.startswith("http"):
                results.append(iframe)

    # hilangkan duplikat
    results = list(dict.fromkeys(results))

    print(f"✅ Total iframe valid: {len(results)}")
    return results

# ============================================================
# 2. Multi-resolve sekali request
# ============================================================
def resolve_multi(iframes):
    print("🚀 Mengirim ke resolver multi-embed...")

    params = [("u", u) for u in iframes]

    r = requests.get(RESOLVER_API, params=params, headers=HEADERS, timeout=200)

    if r.status_code != 200:
        print("🔥 SERVER ERROR:", r.text)
        r.raise_for_status()

    raw = r.json()

    print("🎯 Resolver selesai. Membersihkan output...")

    # Bikin output CLEAN → {iframe: m3u8}
    clean_result = {}

    for iframe in iframes:
        val = raw.get(iframe)

        # Filter nilai tidak valid
        if isinstance(val, str) and ("m3u8" in val):
            clean_result[iframe] = val

    print(f"✨ Stream valid: {len(clean_result)}")
    return clean_result

# ============================================================
# 3. Save JSON rapih
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
