import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote, urlparse, parse_qs, quote
from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ==========================
# Config & Paths
# ==========================
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
AXLIVE_MATCH_BASE_URL = CONFIG.get("AXLIVE_MATCH_BASE_URL")
PROXY_BASE_URL = CONFIG.get("PROXY_BASE_URL")
AXSCORE_LIVE_URL = CONFIG.get("AXSCORE_LIVE_URL")  # ✅ dari config, bukan hardcode


# ==========================
# Utilitas
# ==========================
def masked_url(url, base_url=AXLIVE_MATCH_BASE_URL):
    if url and base_url and url.startswith(base_url):
        return url.replace(base_url, "***")
    return url


# ==========================
# Scrape dari AXSCORE
# ==========================
def get_live_ids_from_axscore():
    """Ambil daftar ID pertandingan yang sedang LIVE dari AXSCORE_LIVE_URL"""
    if not AXSCORE_LIVE_URL:
        print("⚠️ Config 'AXSCORE_LIVE_URL' tidak ditemukan di axlive_file.txt")
        return {}

    headers = {"User-Agent": "Mozilla/5.0"}
    print(f"🔎 Mengambil daftar live dari {AXSCORE_LIVE_URL} ...")

    try:
        res = requests.get(AXSCORE_LIVE_URL, headers=headers, timeout=20)
        res.raise_for_status()
    except Exception as e:
        print(f"⚠️ Gagal mengakses halaman: {e}")
        return {}

    soup = BeautifulSoup(res.text, "html.parser")
    matches = soup.select("a[href*='/match/']")

    live_ids = {}
    for a in matches:
        href = a.get("href", "")
        if "/match/" not in href:
            continue

        # contoh href: /en/match/1234567
        parts = href.split("/")
        if len(parts) >= 3:
            match_id = parts[-1]
            # hanya ambil yang punya indikator LIVE
            live_badge = a.select_one(".match-status, .live, .status")
            if live_badge and "live" in live_badge.get_text(strip=True).lower():
                live_ids[match_id] = datetime.now(ZoneInfo("Asia/Jakarta")).timestamp()

    if not live_ids:
        print("❌ Tidak ada pertandingan LIVE saat ini.")
    else:
        print(f"✅ Ditemukan {len(live_ids)} pertandingan live: {list(live_ids.keys())}")

    return live_ids


# ==========================
# Ambil m3u8 dari halaman AXLive
# ==========================
def extract_tokenized_m3u8(match_id):
    page_url = f"{AXLIVE_MATCH_BASE_URL}/{match_id}?t=suggest"
    final_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        print(f"🔍 Membuka {masked_url(page_url)}")
        page.goto(page_url, timeout=60000)

        def handle_response(response):
            nonlocal final_url
            url = response.url
            if "wowhaha.php" in url and "m3u8=" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                m3u8_raw = unquote(qs.get("m3u8", [""])[0])
                token_full = qs.get("token", [""])[0]

                if "cdn-rum.n2olabs.pro" in m3u8_raw:
                    print("⚠️ Abaikan karena m3u8 sudah self-proxy")
                    return

                parts = token_full.split(".false.")
                if len(parts) == 2:
                    token = parts[0]
                    verify = parts[1]
                    encoded_url = quote(m3u8_raw, safe="")
                    encoded_verify = quote(verify, safe="")
                    final_url = (
                        f"https://cdn-rum.n2olabs.pro/stream.m3u8"
                        f"?url={encoded_url}"
                        f"&token={token}"
                        f"&is_vip=false"
                        f"&verify={encoded_verify}"
                    )
                    print(f"🌟 URL final m3u8:\n{masked_url(final_url, 'https://cdn-rum.n2olabs.pro')}")

        page.on("response", handle_response)
        page.wait_for_timeout(30000)
        browser.close()

    return final_url


# ==========================
# Simpan ke map.json
# ==========================
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

    for idx, (match_id, _) in enumerate(sorted(match_dict.items(), key=lambda x: x[1]), 1):
        print(f"[{idx}/{total}] ▶ Scraping ID: {match_id}")
        try:
            m3u8_url = extract_tokenized_m3u8(match_id)
            if m3u8_url:
                new_data[match_id] = m3u8_url
                print(f"✅ {match_id} berhasil: {masked_url(m3u8_url, 'https://cdn-rum.n2olabs.pro')}")
            else:
                print(f"❌ {match_id} gagal ambil m3u8")
        except Exception as e:
            print(f"❌ Error ID {match_id}: {e}")

    combined = {**old_data, **new_data}
    ordered = {k: combined[k] for k, _ in sorted(match_dict.items(), key=lambda x: x[1]) if k in combined}

    if not MAP_FILE.exists() or json.dumps(ordered, sort_keys=True) != json.dumps(old_data, sort_keys=True):
        with open(MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=2)
        print(f"✅ Disimpan ulang. Total: {len(ordered)} ke {MAP_FILE}")
    else:
        print("ℹ️ Tidak ada perubahan pada map.json.")


# ==========================
# MAIN
# ==========================
if __name__ == "__main__":
    try:
        match_dict = get_live_ids_from_axscore()
        if not match_dict:
            print("⏹ Tidak ada pertandingan live. Skrip dihentikan.")
            exit(0)

        limited = dict(list(match_dict.items())[:10])  # batasi max 10
        save_to_map(limited)

        if not MAP_FILE.exists():
            with open(MAP_FILE, "w") as f:
                json.dump({}, f)
            print("📄 map.json kosong dibuat sebagai fallback.")

    except Exception as e:
        print(f"❌ Fatal Error: {e}")
