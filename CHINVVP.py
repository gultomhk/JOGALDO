import requests
import json
from pathlib import Path

# ==========================
# KONFIG
# ==========================
cvvpdata_FILE = Path.home() / "cvvpdata_file.txt"
config_vars = {}
with open(cvvpdata_FILE, "r", encoding="utf-8") as f:
    exec(f.read(), config_vars)

PPV_API_URL = config_vars["PPV_API_URL"]
RESOLVER_API = config_vars["RESOLVER_API"]

OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

BATCH_SIZE = 10   # aman untuk HF Space


def get_all_iframes():
    print("📺 Fetching PPV.to")

    r = requests.get(PPV_API_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()

    data = r.json()
    out = []

    for cat in data.get("streams", []):
        for s in cat.get("streams", []):
            iframe = s.get("iframe")
            if iframe:
                out.append(iframe)

    print(f"✅ Total iframe found: {len(out)}")
    return out


def resolve_batch(batch):
    """Resolve 1 batch (max 10)"""
    params = []
    for u in batch:
        if u:
            params.append(("u", u))

    print(f"🚀 Resolving batch {len(batch)} items...")

    r = requests.get(
        RESOLVER_API,
        params=params,
        headers=HEADERS,
        timeout=80   # cukup, tidak timeout
    )

    if r.status_code != 200:
        print("🔥 Resolver error:", r.text)
        return {}

    return r.json()


def clean_results(raw: dict) -> dict:
    clean = {}

    for key, val in raw.items():
        if not key or not isinstance(key, str):
            continue
        if not key.startswith("http"):
            continue
        if not val or not isinstance(val, str):
            continue
        if ".m3u8" not in val.lower():
            continue

        clean[key] = val

    return clean


def save_json(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved CLEAN map8.json ({len(data)} entries)")


if __name__ == "__main__":
    all_iframes = get_all_iframes()

    final_map = {}

    # ==========================
    # PROCESS IN BATCHES
    # ==========================
    for i in range(0, len(all_iframes), BATCH_SIZE):
        batch = all_iframes[i:i+BATCH_SIZE]
        try:
            result = resolve_batch(batch)
        except Exception as e:
            print("❌ Batch failed:", e)
            continue

        cleaned = clean_results(result)
        final_map.update(cleaned)

    save_json(final_map)
