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
RESOLVER_API = config_vars.get("RESOLVER_API")   # contoh: http://localhost:7860/multi

OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}


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


def resolve_multi(iframes):
    """Kirim semua iframe ke Playwright resolver 1 kali"""
    print("🚀 Mengirim ke resolver multi-embed...")

    params = []
    for u in iframes:
        # skip data kosong
        if not u or not isinstance(u, str):
            continue
        params.append(("u", u))

    r = requests.get(RESOLVER_API, params=params, headers=HEADERS, timeout=200)

    # kalau server kasih error 400, tampilkan text asli
    if r.status_code != 200:
        print("🔥 SERVER ERROR:", r.text)
        r.raise_for_status()

    result = r.json()
    print("🎯 Resolver selesai.")
    return result


# ==========================
# FILTER BERSIH
# ==========================
def clean_results(raw: dict) -> dict:
    """Filter map8.json → hanya key valid + URL m3u8 saja"""
    clean = {}

    for key, val in raw.items():
        if not key:
            continue
        if not isinstance(key, str):
            continue

        # key harus berupa URL iframe
        if not key.startswith("http"):
            continue

        # value wajib string dan mengandung .m3u8
        if not val or not isinstance(val, str):
            continue
        if ".m3u8" not in val.lower():
            continue

        clean[key] = val

    return clean


def save_json(data):
    cleaned = clean_results(data)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)

    print(f"\n💾 map8.json (BERSIH) berhasil dibuat → {OUTPUT_FILE.absolute()}")
    print(f"📌 Total entry valid: {len(cleaned)}")


if __name__ == "__main__":
    iframes = get_all_iframes()
    results = resolve_multi(iframes)
    save_json(results)
