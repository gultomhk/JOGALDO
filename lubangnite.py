import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote, urlparse, parse_qs, quote
from pathlib import Path
from playwright.sync_api import sync_playwright

# ==============================
# Konfigurasi Awal
# ==============================
AXLIVE_FILE = Path.home() / "axlive_file.txt"
MAP_FILE = Path("map.json")

def load_config(filepath):
    config = {}
    if filepath.exists():
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    key, val = line.split("=", 1)
                    config[key.strip()] = val.strip()
    return config

CONFIG = load_config(AXLIVE_FILE)
AXLIVE_API_URL = CONFIG.get("AXLIVE_API_URL")
AXLIVE_MATCH_BASE_URL = CONFIG.get("AXLIVE_MATCH_BASE_URL")
PROXY_BASE_URL = CONFIG.get("PROXY_BASE_URL")

# ==============================
# Utilitas
# ==============================
def masked_url(url, base_url=AXLIVE_MATCH_BASE_URL):
    if not url or not base_url:
        return url
    return url.replace(base_url, "***") if base_url in url else url


# ==============================
# Ambil daftar match live dari API
# ==============================
def get_live_match_ids():
    headers = {"User-Agent": "Mozilla/5.0"}
    print(f"🔎 Mengambil daftar LIVE dari {AXLIVE_API_URL} ...")

    try:
        res = requests.get(AXLIVE_API_URL, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()

        matches = []
        if isinstance(data, dict):
            matches = data.get("data") or data.get("fixtures") or []
        elif isinstance(data, list):
            matches = data

        if not matches:
            print("❌ Tidak ada pertandingan LIVE saat ini.")
            return {}

        live_dict = {}
        now = datetime.now(ZoneInfo("Asia/Jakarta"))

        for match in matches:
            if not isinstance(match, dict):
                continue

            # Hanya ambil yang benar-benar live
            status = str(match.get("status", "")).upper()
            has_live = match.get("has_live") is True
            playing = match.get("playing") is True

            if not (status == "LIVE" and has_live and playing):
                continue

            match_id = str(match.get("id") or match.get("fixture_id"))
            if not match_id:
                continue

            start_at = match.get("start_at") or match.get("time") or int(now.timestamp())
            live_dict[match_id] = start_at

        if not live_dict:
            print("⚠️ Tidak ditemukan pertandingan dengan status LIVE & aktif.")
            return {}

        print(f"✅ Ditemukan {len(live_dict)} pertandingan LIVE: {', '.join(live_dict.keys())}")
        return dict(sorted(live_dict.items(), key=lambda x: x[1]))

    except Exception as e:
        print(f"⚠️ Gagal mengambil data live: {e}")
        return {}


# ==============================
# Ambil tokenized m3u8
# ==============================
def extract_tokenized_m3u8(page, match_id):
    page_url = f"{AXLIVE_MATCH_BASE_URL}/{match_id}?t=suggest"
    final_url = None
    print(f"🔍 Membuka {masked_url(page_url)}")

    def handle_response(response):
        nonlocal final_url
        url = response.url
        if "wowhaha.php" in url and "m3u8=" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            m3u8_raw = unquote(qs.get("m3u8", [""])[0])
            token_full = qs.get("token", [""])[0]

            if not m3u8_raw or "cdn-rum.n2olabs.pro" in m3u8_raw:
                print("⚠️ Abaikan karena m3u8 sudah self-proxy atau kosong.")
                return

            parts = token_full.split(".false.")
            if len(parts) == 2:
                token, verify = parts
                encoded_url = quote(m3u8_raw, safe="")
                encoded_verify = quote(verify, safe="")

                final_url = (
                    f"https://cdn-rum.n2olabs.pro/stream.m3u8"
                    f"?url={encoded_url}"
                    f"&token={token}"
                    f"&is_vip=false"
                    f"&verify={encoded_verify}"
                )
                print(f"✅ iframe ditemukan untuk {match_id}")

    try:
        page.on("response", handle_response)
        page.goto(page_url, timeout=60000)
        for _ in range(8):
            if final_url:
                break
            page.wait_for_timeout(1000)
    except Exception as e:
        print(f"❌ Gagal load {match_id}: {e}")

    return final_url


# ==============================
# Simpan hasil scraping
# ==============================
def save_to_map(match_dict):
    if not match_dict:
        print("⚠️ Tidak ada data pertandingan.")
        return

    old_data = {}
    if MAP_FILE.exists():
        with open(MAP_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)

    new_data = {}
    total = len(match_dict)

    print(f"\n🚀 Memulai scraping {total} pertandingan dengan Playwright ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        for idx, (match_id, start_at) in enumerate(match_dict.items(), 1):
            print(f"\n[{idx}/{total}] ▶ Scraping ID: {match_id}")
            try:
                m3u8_url = extract_tokenized_m3u8(page, match_id)
                if m3u8_url:
                    new_data[match_id] = m3u8_url
                    print(f"🌟 URL m3u8 berhasil: {masked_url(m3u8_url, 'https://cdn-rum.n2olabs.pro')}")
                else:
                    print(f"❌ {match_id} tidak ada m3u8.")
            except Exception as e:
                print(f"❌ Error ID {match_id}: {e}")

        browser.close()

    combined = {**old_data, **new_data}
    ordered = {k: combined[k] for k in match_dict if k in combined}

    if not MAP_FILE.exists() or json.dumps(ordered, sort_keys=True) != json.dumps(old_data, sort_keys=True):
        with open(MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=2)
        print(f"\n✅ Disimpan ulang. Total: {len(ordered)} ke {MAP_FILE}")
    else:
        print("\nℹ️ Tidak ada perubahan pada map.json.")


# ==============================
# Main eksekusi
# ==============================
if __name__ == "__main__":
    try:
        match_dict = get_live_match_ids()
        save_to_map(match_dict)

        if not MAP_FILE.exists():
            with open(MAP_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
            print("📄 map.json kosong dibuat sebagai fallback.")
    except Exception as e:
        print(f"❌ Fatal Error: {e}")
