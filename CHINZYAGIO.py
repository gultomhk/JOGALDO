import requests
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ==========================
# Load Config
# ==========================
CHINZYAIGODATA_FILE = Path.home() / "chinzyaigodata_file.txt"
config_vars = {}
with open(CHINZYAIGODATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL")
WORKER_URL = config_vars.get("WORKER_URL")
LOGO_URL = config_vars.get("LOGO_URL")
MAIN_URL = config_vars.get("MAIN_URL")
DOMAIN_API = config_vars.get("DOMAIN_API")

# 🕒 Ambil semua pertandingan hari ini (UTC+7)
now = datetime.now(timezone.utc) + timedelta(hours=7)
start = now.replace(hour=0, minute=0, second=0, microsecond=0)
end = now.replace(hour=23, minute=59, second=59, microsecond=0)

OUTPUT_FILE = Path(__file__).parent / "CHINZYAGIO.m3u"

headers = {
    "authority": DOMAIN_API,
    "accept": "*/*",
    "content-type": "application/json",
    "origin": MAIN_URL,
    "referer": f"{MAIN_URL}/trang-chu",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
}

print(f"📅 Rentang waktu (WIB): {start.strftime('%Y-%m-%d %H:%M:%S')} → {end.strftime('%Y-%m-%d %H:%M:%S')}")

all_matches = []
page = 1
limit = 100

# 🔁 Loop otomatis setiap halaman sampai habis
while True:
    payload = {
        "queries": [
            {"field": "start_date", "type": "gte", "value": start.strftime("%Y-%m-%d %H:%M:%S")},
            {"field": "start_date", "type": "lte", "value": end.strftime("%Y-%m-%d %H:%M:%S")},
        ],
        "query_and": True,
        "limit": limit,
        "page": page,
        "order_asc": "start_date",
    }

    print(f"🔎 Mengambil halaman {page}...")

    try:
        resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        matches = data.get("data", [])
        if not matches:
            print("🚫 Tidak ada data di halaman ini, berhenti.")
            break

        print(f"✅ Halaman {page} berisi {len(matches)} pertandingan")
        all_matches.extend(matches)
        page += 1

    except requests.exceptions.RequestException as e:
        print(f"❌ Request error (page {page}): {e}")
        break
    except json.JSONDecodeError:
        print("❌ Response bukan JSON valid")
        print(resp.text)
        break

print(f"\n📦 Total pertandingan terkumpul: {len(all_matches)}\n")

# 🧾 Siapkan file M3U
m3u_lines = ["#EXTM3U"]

for m in all_matches:
    team1 = m.get("team_1", "??")
    team2 = m.get("team_2", "??")
    start_time = m.get("start_date", "")
    stream_id = m.get("id", "unknown")
    league = m.get("league", "").strip()
    desc = m.get("desc", "").strip()

    # 🕒 Konversi waktu UTC → WIB (UTC+7)
    try:
        dt_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_wib = dt_utc + timedelta(hours=7)
        waktu = dt_wib.strftime("%d/%m-%H.%M")
    except Exception:
        waktu = "??"

    group = "⚽️| LIVE EVENT"

    title = f"{waktu} {team1} vs {team2}"
    if league:
        title += f" ({league})"
    elif desc:
        title += f" ({desc})"

    # 🧩 Susun baris M3U
    m3u_lines.append(f'#EXTINF:-1 group-title="{group}" tvg-logo="{LOGO_URL}", {title}')
    m3u_lines.append('#EXTVLCOPT:http-user-agent=Mozilla/5.0 AppleWebKit/537.36 Chrome/81.0.4044.138 Safari/537.36')
    m3u_lines.append(f'#EXTVLCOPT:http-referrer={MAIN_URL}/')
    m3u_lines.append(f'{WORKER_URL}{stream_id}')

# 💾 Simpan ke file M3U
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(m3u_lines))

print(f"🎉 File M3U berhasil dibuat: {OUTPUT_FILE} (Zona waktu WIB)")
