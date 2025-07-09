import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import unquote, urlparse, parse_qs
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MAP_FILE = Path("map.json")

AXLIVE_LIVESTREAM_URL = os.getenv("AXLIVE_LIVESTREAM_URL")
AXLIVE_FEATURED_URL = os.getenv("AXLIVE_FEATURED_URL")
AXLIVE_LIVESTREAM_SPORT3_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT3_URL")
AXLIVE_MATCH_BASE_URL = os.getenv("AXLIVE_MATCH_BASE_URL")


def get_live_match_ids():
    urls = {
        "main": (AXLIVE_LIVESTREAM_URL, True),       # Apply time filter
        "featured": (AXLIVE_FEATURED_URL, False),     # No time filter
        "sport3": (AXLIVE_LIVESTREAM_SPORT3_URL, True),  # Apply time filter
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    print("🔎 Mengambil ID dari API jadwal...")
    combined_dict = {}
    seen_ids = set()
    now = datetime.now(ZoneInfo("Asia/Jakarta"))

    for label, (url, apply_time_filter) in urls.items():
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            json_data = res.json()
            matches = json_data.get("data", [])

            live_matches = {}
            upcoming_matches = {}

            for match in matches:
                try:
                    if not match.get("has_live"):
                        continue

                    match_id = str(match.get("id"))
                    if not match_id or match_id in seen_ids:
                        continue

                    start_at = match.get("start_at")
                    if not start_at:
                        continue

                    event_time_utc = datetime.fromtimestamp(start_at, ZoneInfo("UTC"))
                    event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

                    if apply_time_filter and event_time_local < (now - timedelta(hours=2)):
                        continue

                    status = match.get("status", "").upper()

                    if status == "LIVE":
                        live_matches[match_id] = start_at
                    else:
                        upcoming_matches[match_id] = start_at

                    seen_ids.add(match_id)

                except Exception as e:
                    print(f"❌ Error parsing match: {e}")

            # Ambil max 5 LIVE + 5 Upcoming dari masing-masing kategori
            combined = dict(
                list(sorted(live_matches.items(), key=lambda x: x[1]))[:5] +
                list(sorted(upcoming_matches.items(), key=lambda x: x[1]))[:5]
            )

            print(f"✅ {label}: {list(combined.keys())}")
            combined_dict.update(combined)

        except Exception as e:
            print(f"⚠️ Gagal fetch dari {label}: {e}")

    # Gabungkan semua hasil dan urutkan berdasarkan waktu mulai
    final_sorted = dict(sorted(combined_dict.items(), key=lambda x: x[1]))
    print(f"🎯 Total ID gabungan: {list(final_sorted.keys())}")
    return final_sorted

def extract_tokenized_m3u8(match_id):
    page_url = f"{AXLIVE_MATCH_BASE_URL}/{match_id}?t=suggest"
    final_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        print(f"🔍 Membuka {page_url}")
        page.goto(page_url, timeout=60000)

        def handle_response(response):
            url = response.url
            if "wowhaha.php" in url and "m3u8=" in url:
                print(f"✅ Ditemukan iframe:\n{url}")
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)

                m3u8_raw = unquote(qs.get("m3u8", [""])[0])
                token_full = qs.get("token", [""])[0]

                parts = token_full.split(".false.")
                if len(parts) == 2:
                    token = parts[0]
                    verify = parts[1]
                    nonlocal final_url
                    final_url = f"{m3u8_raw}?token={token}&is_vip=false&verify={verify}"
                    print(f"🌟 URL final m3u8:\n{final_url}")

        page.on("response", handle_response)
        page.wait_for_timeout(30000)
        browser.close()
        return final_url


def save_to_map(match_dict):
    old_data = {}
    if MAP_FILE.exists():
        with open(MAP_FILE) as f:
            old_data = json.load(f)

    new_data = {}
    total = len(match_dict)
    for idx, (match_id, start_at) in enumerate(sorted(match_dict.items(), key=lambda x: x[1]), 1):
        if match_id in old_data:
            print(f"⏭ Lewati ID: {match_id} (sudah ada)")
            new_data[match_id] = old_data[match_id]
            continue

        print(f"[{idx}/{total}] ▶ Scraping ID: {match_id}")
        try:
            m3u8 = extract_tokenized_m3u8(match_id)
            if m3u8:
                new_data[match_id] = m3u8
                print(f"✅ {match_id} berhasil: {m3u8}")
            else:
                print(f"❌ {match_id} gagal ambil m3u8")
        except Exception as e:
            print(f"❌ Error ID {match_id}: {e}")

    combined_data = {**old_data, **new_data}
    ordered_data = dict(sorted(combined_data.items(), key=lambda x: match_dict.get(x[0], 0)))

    with open(MAP_FILE, "w") as f:
        json.dump(ordered_data, f, indent=2)

    print(f"✅ Semua selesai. Total tersimpan: {len(ordered_data)} ke {MAP_FILE}")


if __name__ == "__main__":
    match_dict = get_live_match_ids()
    limited_matches = dict(list(match_dict.items())[:5])
    save_to_map(limited_matches)
