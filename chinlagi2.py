#!/usr/bin/env python3
import requests
import json
import re
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator
from pathlib import Path

# ==========================
# Load Config
# ==========================
CHINLAGI2DATA_FILE = Path.home() / "chinlagi2data_file.txt"

config_vars = {}
with open(CHINLAGI2DATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

UA = config_vars.get("UA")
REFERER = config_vars.get("REFERER")
WORKER_PROXY = config_vars.get("WORKER_PROXY")
DEFAULT_LOGO = config_vars.get("DEFAULT_LOGO")
BASE_URL = config_vars.get("BASE_URL")

OUT_FILE = "CHIN2_matches.m3u"  

# ===== AUTO TANGGAL (GMT+7) =====
tz_jakarta = timezone(timedelta(hours=7))
today = datetime.now(tz_jakarta)
json_filename = f"matches_{today.strftime('%Y%m%d')}.json"
JSON_URL = BASE_URL + json_filename

headers = {
    "User-Agent": UA,
    "Referer": REFERER,
}

print(f"🕓 Fetching: {JSON_URL}")

# ===== FETCH DAN BERSIHKAN JSON =====
resp = requests.get(JSON_URL, headers=headers, timeout=15)
resp.raise_for_status()
raw_text = resp.text.strip()

# hapus pembungkus seperti matches_20251025({...})
json_text = re.sub(r'^[^(]+\(|\)\s*$', '', raw_text)
data = json.loads(json_text)

matches = data.get("data", [])
if not matches:
    print("⚠️ Tidak ada data match ditemukan.")
    exit()

# ===== Inisialisasi Translator (CN → EN) =====
translator = GoogleTranslator(source="auto", target="en")

# Cache sederhana biar gak terjemah teks yang sama berulang
translate_cache = {}

def tr(text: str):
    """Terjemahkan teks dengan cache."""
    if not text:
        return text
    if text in translate_cache:
        return translate_cache[text]
    try:
        translated = translator.translate(text)
    except Exception:
        translated = text
    translate_cache[text] = translated
    return translated


# ===== BUILD OUTPUT M3U =====
lines = ["#EXTM3U"]

for match in matches:
    host = match.get("hostName", "TBD")
    guest = match.get("guestName", "TBD")
    league = match.get("subCateName", match.get("categoryName", ""))
    match_ts = match.get("matchTime", 0)

    # format waktu ke WIB
    dt = datetime.fromtimestamp(match_ts / 1000, tz=tz_jakarta)
    time_str = dt.strftime("%d/%m-%H.%M")

    # 🔠 Terjemahkan nama tim & liga
    host_en = tr(host)
    guest_en = tr(guest)
    league_en = tr(league)

    anchors = match.get("anchors", [])
    if not anchors:
        continue

    for anchor in anchors:
        uid = anchor.get("uid")
        nick = anchor.get("nickName", "Unknown")
        icon = anchor.get("cutOutIcon") or anchor.get("icon") or LOGO_DEFAULT

        title = f"{host_en} vs {guest_en}"
        extinf = (
            f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" '
            f'tvg-logo="{icon}",{time_str} {title} ({league_en}) • {nick}'
        )

        lines.append(extinf)
        lines.append(f"#EXTVLCOPT:http-user-agent={UA}")
        lines.append(f"#EXTVLCOPT:http-referrer={REFERER}")
        lines.append(f"{WORKER_PROXY}/?uid={uid}")
        lines.append("")  # newline antar anchor

# ===== SIMPAN KE FILE =====
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"✅ File M3U berhasil dibuat: {OUT_FILE}")
print(f"📦 Total pertandingan: {len(matches)}")
