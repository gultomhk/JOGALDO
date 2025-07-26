import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import unquote, urlparse, parse_qs, quote
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MAP_FILE = Path("map.json")
AXLIVE_LIVESTREAM_URL = os.getenv("AXLIVE_LIVESTREAM_URL")
AXLIVE_FEATURED_URL = os.getenv("AXLIVE_FEATURED_URL")
AXLIVE_LIVESTREAM_SPORT3_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT3_URL")
AXLIVE_LIVESTREAM_SPORT4_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT4_URL")
AXLIVE_LIVESTREAM_SPORT5_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT5_URL")
AXLIVE_LIVESTREAM_SPORT6_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT6_URL")
AXLIVE_LIVESTREAM_SPORT7_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT7_URL")
AXLIVE_LIVESTREAM_SPORT8_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT8_URL")
AXLIVE_LIVESTREAM_SPORT9_URL = os.getenv("AXLIVE_LIVESTREAM_SPORT9_URL")
AXLIVE_MATCH_BASE_URL = os.getenv("AXLIVE_MATCH_BASE_URL")
PROXY_BASE_URL = os.getenv("PROXY_BASE_URL")


def get_live_match_ids():
    urls = {
        "main": (AXLIVE_LIVESTREAM_URL, True),
        "featured": (AXLIVE_FEATURED_URL, False),
        "sport3": (AXLIVE_LIVESTREAM_SPORT3_URL, True),
        "sport4": (AXLIVE_LIVESTREAM_SPORT4_URL, True),
        "sport5": (AXLIVE_LIVESTREAM_SPORT5_URL, False),
    }

    headers = {"User-Agent": "Mozilla/5.0"}
    print("🔎 Mengambil ID dari API jadwal...")

    combined_dict = {}
    seen_ids = set()
    now = datetime.now(ZoneInfo("Asia/Jakarta"))

    for label, (url, apply_time_filter) in urls.items():
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            matches = res.json().get("data", [])

            live_matches, upcoming_matches = {}, {}

            for match in matches:
                if not match.get("has_live"):
                    continue

                match_id = str(match.get("id"))
                if not match_id or match_id in seen_ids:
                    continue

                start_at = match.get("start_at")
                if not start_at:
                    continue

                time_local = datetime.fromtimestamp(start_at, ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Jakarta"))
                if apply_time_filter and time_local < (now - timedelta(hours=2)):
                    continue

                status = match.get("status", "").upper()
                (live_matches if status == "LIVE" else upcoming_matches)[match_id] = start_at
                seen_ids.add(match_id)

            combined = dict(
                list(sorted(live_matches.items(), key=lambda x: x[1]))[:10] +
                list(sorted(upcoming_matches.items(), key=lambda x: x[1]))[:10]
            )

            print(f"✅ {label}: {list(combined.keys())}")
            combined_dict.update(combined)

        except Exception as e:
            print(f"⚠️ Gagal fetch dari {label}: {e}")

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
            nonlocal final_url
            url = response.url

            if "wowhaha.php" in url and "m3u8=" in url:
                print(f"✅ Ditemukan iframe:\n{url}")
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
                    print(f"🌟 URL final m3u8:\n{final_url}")

        page.on("response", handle_response)
        page.wait_for_timeout(30000)
        browser.close()

    return final_url

def save_to_map(match_dict):
    if not match_dict:
        print("⚠️ Tidak ada match yang diberikan.")
        return

    old_data = {}
    if MAP_FILE.exists():
        with open(MAP_FILE, encoding="utf-8") as f:
            old_data = json.load(f)

    new_data = {}
    for idx, (match_id, start_at) in enumerate(sorted(match_dict.items(), key=lambda x: x[1]), 1):
        print(f"[{idx}/{len(match_dict)}] ▶ Scraping ID: {match_id}")
        try:
            m3u8_url = extract_tokenized_m3u8(match_id)
            if m3u8_url:
                new_data[match_id] = m3u8_url
                print(f"✅ {match_id} berhasil: {m3u8_url}")
            else:
                print(f"❌ {match_id} gagal ambil m3u8")
        except Exception as e:
            print(f"❌ Error ID {match_id}: {e}")

    # Gabungkan data lama dan baru
    combined_data = {**old_data, **new_data}

    # Urutkan berdasarkan waktu dari match_dict (jika tidak ada waktu, pakai 0)
    combined_sorted = dict(sorted(combined_data.items(), key=lambda x: match_dict.get(x[0], 0)))

    # ⚠️ Jika ingin batasi 100 entri terakhir, aktifkan baris ini:
    # combined_sorted = dict(list(combined_sorted.items())[-100:])

    # Simpan hanya jika berbeda
    if not MAP_FILE.exists() or combined_sorted != old_data:
        with open(MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(combined_sorted, f, indent=2)
        print(f"✅ Tersimpan {len(combined_sorted)} entri ke {MAP_FILE}")
    else:
        print("ℹ️ Tidak ada perubahan pada map.json.")

if __name__ == "__main__":
    try:
        match_dict = get_live_match_ids()

        # Selalu proses semua ID tanpa filter
        limited = dict(list(match_dict.items())[:15])

        save_to_map(limited)

        # Fallback terakhir
        if not MAP_FILE.exists():
            with open(MAP_FILE, "w") as f:
                json.dump({}, f)
            print("📄 map.json kosong dibuat sebagai fallback.")

    except Exception as e:
        print(f"❌ Fatal Error: {e}")
