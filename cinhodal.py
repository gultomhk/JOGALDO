import requests
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo  # Python 3.9+
from pathlib import Path

# Path ke file config
CONFIG_FILE = Path.home() / "sterame3data_file.txt"

# --- Load konfigurasi dari file ---
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

# Assign variabel dari config
MATCHES_URL = config_globals.get("MATCHES_URL")
STREAM_URL = config_globals.get("STREAM_URL")
WORKER_URL = config_globals.get("WORKER_URL")
LOGO_URL = config_globals.get("LOGO_URL")
VLC_OPTS = config_globals.get("VLC_OPTS")
USER_AGENT = config_globals.get("USER_AGENT")
HEADERS = config_globals.get("HEADERS")

# Kategori yang dilewatkan filter waktu
EXEMPT_CATEGORIES = [
    "fight",
    "motor-sports",
    "tennis"
]

def fetch_stream(source_type, source_id):
    try:
        url = STREAM_URL.format(source_type, source_id)
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"⚠️ gagal fetch stream {source_type}/{source_id}: {e}")
        return []

def main(apply_time_filter=True):
    res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
    matches = res.json()

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))
    playlist = "#EXTM3U\n"

    tasks = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
        for match in matches:
            # konversi waktu event
            start_at = match["date"] / 1000
            event_time_utc = datetime.datetime.fromtimestamp(start_at, ZoneInfo("UTC"))
            event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

            # filter waktu lewat 2 jam (kecuali kategori tertentu)
            category = match.get("category", "").lower()
            if apply_time_filter and category not in EXEMPT_CATEGORIES:
                if event_time_local < (now - datetime.timedelta(hours=2)):
                    continue

            match_time_str = event_time_local.strftime("%d/%m-%H.%M")

            # pilih judul
            teams = match.get("teams")
            if teams and "home" in teams and "away" in teams:
                display_title = f"{teams['home']['name']} vs {teams['away']['name']}"
            else:
                raw_title = match.get("title", "Unknown Match")
                if ":" in raw_title:
                    loc, contest = raw_title.split(":", 1)
                    display_title = f"{loc.strip()}  {contest.strip()}"
                else:
                    display_title = raw_title

            # submit task fetch stream
            for src in match.get("sources", []):
                source_type, source_id = src["source"], src["id"]
                fut = executor.submit(fetch_stream, source_type, source_id)
                tasks[fut] = (match_time_str, display_title, source_type)

        # proses hasil fetch
        for fut in as_completed(tasks):
            match_time_str, display_title, source_type = tasks[fut]
            streams = fut.result()

            if not streams:
                continue

            # Ambil hanya server 1
            stream = streams[0]
            stream_no = stream.get("streamNo", 1)
            if stream_no != 1:
                stream_no = 1  # pastikan server tetap 1

            server_name = f"{source_type} server {stream_no}"
            slug = f"{source_type}/{stream['id']}/{stream_no}"

            playlist += (
                f'#EXTINF:-1 tvg-logo="{LOGO_URL}" group-title="⚽️| LIVE EVENT",{match_time_str}  {display_title} {server_name}\n'
                f"{VLC_OPTS}"
                f"{WORKER_URL.format(slug)}\n\n"
            )

    with open("schedule_today.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)

    print("✅ schedule_today.m3u berhasil dibuat")

if __name__ == "__main__":
    main()
