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
AXLIVE_MATCH_BASE_URL = os.getenv("AXLIVE_MATCH_BASE_URL")
PROXY_BASE_URL = os.getenv("PROXY_BASE_URL")

def get_live_match_ids():
    urls = {
        "main": (AXLIVE_LIVESTREAM_URL, True),
        "featured": (AXLIVE_FEATURED_URL, False),
        "sport3": (AXLIVE_LIVESTREAM_SPORT3_URL, True),
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

from urllib.parse import urlparse, parse_qs, unquote, quote

def extract_tokenized_m3u8(match_id):
    page_url = f"{AXLIVE_MATCH_BASE_URL}/{match_id}?t=suggest"
    found_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        print(f"🔍 Membuka {page_url}")
        page.goto(page_url, timeout=60000)

        def handle_response(response):
            nonlocal found_url
            url = response.url
            if "wowhaha.php" in url and "m3u8=" in url:
                print(f"✅ Ditemukan iframe:\n{url}")
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)

                m3u8_raw = unquote(qs.get("m3u8", [""])[0])
                token_full = qs.get("token", [""])[0]

                if "cdn-rum.n2olabs.pro" in m3u8_raw:
                    print("⚠️ Abaikan URL self-proxy, m3u8 sudah melalui proxy")
                    return

                parts = token_full.split(".false.")
                if len(parts) == 2:
                    token = parts[0]
                    verify = quote(parts[1], safe="")  # Encode agar + tetap + (%2B)

                    encoded_url = quote(m3u8_raw, safe="")
                    found_url = (
                        f"{PROXY_BASE_URL}?url={encoded_url}"
                        f"&token={token}&is_vip=false&verify={verify}"
                    )
                    print(f"🌟 URL final m3u8:\n{found_url}")

        page.on("response", handle_response)
        page.wait_for_timeout(30000)
        browser.close()

    return found_url

def to_proxy_url(raw_url):
    parsed = urlparse(raw_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    qs = parse_qs(parsed.query)

    token = qs.get("token", [""])[0]
    verify = quote(qs.get("verify", [""])[0], safe="")  # Encode ulang verify
    is_vip = qs.get("is_vip", ["false"])[0]
    encoded_base = quote(base_url, safe="")

    return (
        f"{PROXY_BASE_URL}?url={encoded_base}"
        f"&token={token}"
        f"&is_vip={is_vip}"
        f"&verify={verify}"
    )

def save_to_map(match_dict):
    old_data = {}
    if MAP_FILE.exists():
        with open(MAP_FILE) as f:
            old_data = json.load(f)

    new_data = {}
    total = len(match_dict)

    for idx, (match_id, start_at) in enumerate(sorted(match_dict.items(), key=lambda x: x[1]), 1):
        print(f"[{idx}/{total}] ▶ Scraping ID: {match_id}")
        try:
            m3u8 = extract_tokenized_m3u8(match_id)
            if m3u8:
                proxy_url = to_proxy_url(m3u8)
                new_data[match_id] = proxy_url
                print(f"✅ {match_id} berhasil: {proxy_url}")
            else:
                print(f"❌ {match_id} gagal ambil m3u8")
        except Exception as e:
            print(f"❌ Error ID {match_id}: {e}")

    combined_data = {**old_data, **new_data}
    ordered_data = dict(sorted(combined_data.items(), key=lambda x: match_dict.get(x[0], 0)))

    if ordered_data != old_data:
        with open(MAP_FILE, "w") as f:
            json.dump(ordered_data, f, indent=2)
        print(f"✅ Semua selesai. Total tersimpan: {len(ordered_data)} ke {MAP_FILE}")
    else:
        print("ℹ️ Tidak ada perubahan pada map.json. Skip commit dan push.")
    
if __name__ == "__main__":
    try:
        match_dict = get_live_match_ids()

        # Ambil ID yang sudah diproses
        done_ids = []
        if MAP_FILE.exists():
            with open(MAP_FILE) as f:
                done_ids = list(json.load(f).keys())

        # Ambil hanya ID baru yang belum ada
        pending = {k: v for k, v in match_dict.items() if k not in done_ids}

        # Ambil maksimal 10 ID berikutnya untuk diproses
        limited = dict(list(pending.items())[:10])

        save_to_map(limited)
    except Exception as e:
        print(f"❌ Fatal Error: {e}")
