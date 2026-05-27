import requests
import sys
import urllib3
import re
from pathlib import Path

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


# ===============================
# PLAYLIST 1 (AMBIL SEMUA DATA)
# ===============================
print("\n▶️ Mengambil playlist 1...")

playlist1_text = fetch_playlist(API_URL)

if not playlist1_text:
    print("[!] Playlist 1 gagal diambil")
    sys.exit()

print("✅ Playlist 1 berhasil diambil")

# hapus header bawaan
output1 = []

for line in playlist1_text.splitlines():

    if line.strip().startswith("#EXTM3U"):
        continue

    output1.append(line)


# ===============================
# GANTI GROUP TITLE
# ===============================
def replace_group_title(content: str, new_group: str):

    pattern = r'group-title="[^"]*"'

    replaced = re.sub(
        pattern,
        f'group-title="{new_group}"',
        content
    )

    return replaced


# ===============================
# PLAYLIST 2 (SEMUA GROUP DIGANTI)
# ===============================
print("\n▶️ Mengambil playlist 2...")

playlist2_text = fetch_playlist(API_URL2)

if not playlist2_text:
    print("[!] Playlist 2 gagal diambil")
    sys.exit()

print("▶️ Mengganti semua group-title playlist 2...")

modified_playlist2 = replace_group_title(
    playlist2_text,
    "🧧|CH CUBMU2"
)

# hapus header playlist2
playlist2_lines = []

for line in modified_playlist2.splitlines():

    if line.strip().startswith("#EXTM3U"):
        continue

    playlist2_lines.append(line)


# ===============================
# GABUNGKAN OUTPUT
# ===============================
final_output = []

# header utama
final_output.append("#EXTM3U")
final_output.append("")

# playlist 1
final_output.extend(output1)

# playlist 2
final_output.append("")
final_output.extend(playlist2_lines)

# ===============================
# SIMPAN FILE
# ===============================
OUTPUT_FILE = "ZIGZAGO.m3u"

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(final_output))

print(f"\n✅ Berhasil simpan {OUTPUT_FILE}")
