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
RESOLVER_API = config_vars.get("RESOLVER_API")


OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

def extract_m3u8(text):
    """Ekstrak URL .m3u8 dari respon"""
    m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', text)
    return m.group(0) if m else None


def get_all_iframes():
    """Ambil semua iframe URL dari API ppv.to"""
    print("📺 Mengambil event dari PPV.to...")

    r = requests.get(PPV_API_URL, headers=HEADERS, timeout=15)
    data = r.json()

    results = []
    for category in data.get("streams", []):
        for stream in category.get("streams", []):
            iframe = stream.get("iframe")
            if iframe:
                results.append(iframe)

    print(f"✅ Total iframe ditemukan: {len(results)}")
    return results


def resolve_all(iframes):
    """Coba semua iframe satu-per-satu ke HF resolver"""
    output = {}

    for iframe in iframes:
        url = RESOLVER_API + iframe
        print(f"🔍 Resolving: {iframe}")

        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            m3u8 = extract_m3u8(r.text)

            if m3u8:
                print(f"   → ✅ Berhasil: {m3u8}")
                output[iframe] = m3u8
            else:
                print("   → ❌ Tidak menemukan .m3u8")
                output[iframe] = None

        except Exception as e:
            print(f"   → ❌ Error: {e}")
            output[iframe] = None

    return output


def save_json(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n💾 map8.json berhasil dibuat ({OUTPUT_FILE.absolute()})")


if __name__ == "__main__":
    iframes = get_all_iframes()
    results = resolve_all(iframes)
    save_json(results)
