import requests
import sys
import urllib3
import json
import re
import base64
import ast
from pathlib import Path
from hashlib import pbkdf2_hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================
# KONFIGURASI
# ==========================
cvvpdata_FILE = Path.home() / "cvvpdata_file.txt"
config_vars = {}

try:
    with open(cvvpdata_FILE, "r", encoding="utf-8") as f:
        code = f.read()
        exec(code, config_vars)

except Exception as e:
    print(f"[!] Gagal membaca config: {e}")
    sys.exit()

API_URL = config_vars.get("API_URL")
API_URL2 = config_vars.get("API_URL2")

if not API_URL:
    print("[!] API_URL tidak ditemukan di config")
    sys.exit()

if not API_URL2:
    print("[!] API_URL2 tidak ditemukan di config")
    sys.exit()

# ==========================
# PLAYLIST 3 CONFIG
# ==========================

TARGET_URL = config_vars.get("TARGET_URL")
SHAKA_URL = config_vars.get("SHAKA_URL")
MOVIN_URL = config_vars.get("MOVIN_URL")
JSON_URL = config_vars.get("JSON_URL")
REPLAY_WORKER = config_vars.get("REPLAY_WORKER")
PASSWORD = config_vars.get("PASSWORD")
SALT = config_vars.get("SALT")
ITERATIONS = config_vars.get("ITERATIONS")

if not TARGET_URL:
    print("[!] TARGET_URL tidak ditemukan di config")
    sys.exit()

if not PASSWORD:
    print("[!] PASSWORD tidak ditemukan di config")
    sys.exit()

if not SALT:
    print("[!] SALT tidak ditemukan di config")
    sys.exit()

if not ITERATIONS:
    print("[!] ITERATIONS tidak ditemukan di config")
    sys.exit()

# ==========================
# FETCH PLAYLIST
# ==========================
def fetch_playlist(url):

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30,
            verify=False
        )

        response.raise_for_status()

        return response.text

    except Exception as e:
        print(f"[!] Gagal fetch: {url}")
        print(e)
        return None



# ==========================
# PLAYLIST 4 (REPLAY)
# ==========================
def get_playlist4():

    try:

        print("\n▶️ Mengambil Playlist 4...")

        UA = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/534.24 (KHTML, like Gecko) "
            "Chrome/11.0.696.34 Safari/534.24"
        )

        r = requests.get(
            JSON_URL,
            headers={"User-Agent": UA},
            timeout=30,
            verify=False
        )

        r.raise_for_status()
        data = r.json()

        playlist = []
        total_ok = 0

        for item in data:

            title = item.get("title", "").strip()
            logo = item.get("image", "").strip()
            replay_id = item.get("id")

            if replay_id is None:
                continue

            playlist.extend([
                f'#EXTINF:-1 tvg-logo="{logo}" group-title="⚽⚽⚽| TV REPLAY WORLDCUP 2026",{title}',
                f'#EXTVLCOPT:http-user-agent={UA}',
                f'{REPLAY_WORKER}/?id={replay_id}'
            ])

            total_ok += 1

        print(f"✅ Playlist 4 selesai ({total_ok} replay)")
        return playlist

    except Exception as e:

        print(f"[!] Playlist 4 gagal: {e}")
        return []

# ===============================
# PLAYLIST 1 (AMBIL SEMUA DATA)
# ===============================
print("\n▶️ Mengambil playlist 1...")

playlist1_text = fetch_playlist(API_URL)

if not playlist1_text:
    print("[!] Playlist 1 gagal diambil")
    sys.exit()

print("✅ Playlist 1 berhasil diambil")

output1 = []

for line in playlist1_text.splitlines():

    if line.strip().startswith("#EXTM3U"):
        continue

    output1.append(line)


# ===============================
# GANTI GROUP TITLE
# ===============================
def replace_group_title(content, new_group):

    pattern = r'group-title="[^"]*"'

    return re.sub(
        pattern,
        f'group-title="{new_group}"',
        content
    )


# ===============================
# PLAYLIST 4
# ===============================
playlist4_lines = get_playlist4()


# ===============================
# GABUNGKAN OUTPUT
# ===============================
final_output = []

final_output.append("#EXTM3U")
final_output.append("")

# Playlist 1
final_output.extend(output1)

# Playlist 4
if playlist4_lines:
    final_output.append("")
    final_output.extend(playlist4_lines)

# ===============================
# SIMPAN FILE
# ===============================
OUTPUT_FILE = "ZIGZAGO.m3u"

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    f.write("\n".join(final_output))

print(f"\n✅ Berhasil simpan {OUTPUT_FILE}")
