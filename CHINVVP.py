import requests
import json
from pathlib import Path
import time

# ==========================
# KONFIGURASI
# ==========================
cvvpdata_FILE = Path.home() / "cvvpdata_file.txt"
config_vars = {}

with open(cvvpdata_FILE, "r", encoding="utf-8") as f:
    exec(f.read(), config_vars)

PPV_API_URL = config_vars.get("PPV_API_URL")
RESOLVER_API = config_vars.get("RESOLVER_API")

OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

BATCH_SIZE = 12     
RETRY = 3          

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
            if iframe:
                results.append(iframe)

    print(f"✅ Total iframe ditemukan: {len(results)}")
    return results

# ============================================================
def resolve_batch(batch):
    """Resolve batch kecil supaya tidak timeout"""
    params = [("u", u) for u in batch]

    for attempt in range(RETRY):
        try:
            r = requests.get(
                RESOLVER_API,
                params=params,
                headers=HEADERS,
                timeout=40,
            )
            if r.status_code != 200:
                print("🔥 ERROR:", r.text)
                r.raise_for_status()

            return r.json()

        except Exception as e:
            print(f"⚠️ Timeout (attempt {attempt+1}/{RETRY}) → {e}")
            time.sleep(3)

    print("❌ Gagal resolve batch setelah retry")
    return {}

# ============================================================
def resolve_all(iframes):
    print("🚀 Memulai multi-resolve dalam batch…")

    all_results = {}
    total = len(iframes)

    for i in range(0, total, BATCH_SIZE):
        batch = iframes[i:i + BATCH_SIZE]
        print(f"\n📦 Batch {i//BATCH_SIZE+1} → {len(batch)} iframe")

        result = resolve_batch(batch)

        # merge ke output final
        for key, val in result.items():
            all_results[key] = val

        time.sleep(1)  # jeda kecil supaya aman

    print("\n🎯 Semua batch selesai.")
    return all_results

# ============================================================
def save_json(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n💾 map8.json berhasil dibuat → {OUTPUT_FILE.absolute()}")

# ============================================================
if __name__ == "__main__":
    iframes = get_all_iframes()
    results = resolve_all(iframes)
    save_json(results)
