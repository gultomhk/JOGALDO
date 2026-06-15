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
# AES GCM DECRYPT
# ==========================
def derive_key():

    return pbkdf2_hmac(
        "sha256",
        PASSWORD.encode(),
        SALT,
        ITERATIONS,
        dklen=32
    )


def extract_enc_values(text):

    enc_data_match = re.search(
        r'ENC_DATA\s*=\s*"([^"]+)"',
        text
    )

    enc_iv_match = re.search(
        r'ENC_IV\s*=\s*"([^"]+)"',
        text
    )

    if not enc_data_match or not enc_iv_match:
        raise ValueError("ENC_DATA / ENC_IV tidak ditemukan")

    return (
        enc_data_match.group(1),
        enc_iv_match.group(1)
    )


def decrypt_data(enc_data, enc_iv):

    key = derive_key()

    ciphertext = base64.b64decode(enc_data)
    iv = base64.b64decode(enc_iv)

    aesgcm = AESGCM(key)

    plaintext = aesgcm.decrypt(
        iv,
        ciphertext,
        None
    )

    return plaintext.decode("utf-8")


# ==========================
# PLAYLIST 3
# ==========================
def get_playlist3():

    try:

        print("\n▶️ Mengambil Playlist 3...")

        UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        )

        r = requests.get(
            TARGET_URL,
            timeout=30,
            headers={
                "User-Agent": UA
            },
            verify=False
        )

        r.raise_for_status()

        text = r.text

        # =====================
        # Ambil uel1 - uel4
        # =====================
        all_ids = []

        for key_name in (
            "uel1",
            "uel2",
            "uel3",
            "uel4"
        ):

            m = re.search(
                rf'"{key_name}"\s*:\s*(\[[^\]]+\])',
                text,
                re.S
            )

            if not m:
                continue

            try:

                ids = json.loads(
                    m.group(1)
                )

                print(
                    f"[+] Total ID {key_name}: {len(ids)}"
                )

                all_ids.extend(ids)

            except Exception as e:

                print(
                    f"[!] Gagal parsing {key_name}: {e}"
                )

        channel_ids = list(
            dict.fromkeys(all_ids)
        )

        print(
            f"[+] Total unique ID: {len(channel_ids)}"
        )

        playlist = []
        total_ok = 0

        for channel_id in channel_ids:

            try:

                print(
                    f"   ↳ {channel_id}"
                )

                player_name = (
                    channel_id.upper()
                )

                mpd_url = ""
                drm_key = ""

                # =====================
                # SHAKA
                # =====================
                try:

                    response = requests.get(
                        SHAKA_URL.format(
                            channel_id
                        ),
                        headers={
                            "User-Agent": UA
                        },
                        timeout=20,
                        verify=False
                    )

                    response.raise_for_status()

                    enc_data, enc_iv = (
                        extract_enc_values(
                            response.text
                        )
                    )

                    if not enc_data:
                        raise Exception(
                            "ENC_DATA tidak ditemukan"
                        )

                    if not enc_iv:
                        raise Exception(
                            "ENC_IV tidak ditemukan"
                        )

                    decrypted = decrypt_data(
                        enc_data,
                        enc_iv
                    )

                    match = re.search(
                        r'initializePlayer\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]',
                        decrypted,
                        re.S
                    )

                    if not match:
                        raise Exception(
                            "initializePlayer tidak ditemukan"
                        )

                    player_name = (
                        match.group(1)
                        .strip()
                    )

                    mpd_url = (
                        match.group(2)
                        .strip()
                    )

                    drm_key = (
                        match.group(3)
                        .strip()
                    )

                    print(
                        "      ✅ SHAKA"
                    )

                except Exception as shaka_error:

                    print(
                        f"      ⚠ SHAKA gagal: {shaka_error}"
                    )

                    print(
                        "      🔄 Fallback BITMOVIN..."
                    )

                    payload = requests.get(
                        MOVIN_URL.format(
                            channel_id
                        ),
                        headers={
                            "User-Agent": UA
                        },
                        timeout=20,
                        verify=False
                    ).json()

                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=SALT,
                        iterations=ITERATIONS,
                    )

                    aes_key = kdf.derive(
                        PASSWORD.encode()
                    )

                    iv = base64.b64decode(
                        payload["iv"]
                    )

                    ciphertext = base64.b64decode(
                        payload["data"]
                    )

                    plain = AESGCM(
                        aes_key
                    ).decrypt(
                        iv,
                        ciphertext,
                        None
                    )

                    plain_text = (
                        plain.decode()
                        .strip()
                    )

                    try:

                        data = json.loads(
                            plain_text
                        )

                    except Exception:

                        data = ast.literal_eval(
                            plain_text
                        )

                    mpd_url = (
                        data.get("dash")
                        or data.get("hls")
                        or data.get("mpd")
                        or data.get("manifest")
                        or ""
                    )

                    drm_key = data.get(
                        "drm",
                        ""
                    )

                    print(
                        f"      ✅ BITMOVIN ({'HLS' if 'hls' in data else 'DASH'})"
                    )

                # =====================
                # VALIDASI
                # =====================
                if not mpd_url:
                    raise Exception(
                        "MPD kosong"
                    )

                if ":" not in drm_key:
                    raise Exception(
                        "DRM invalid"
                    )

                kid, key = drm_key.split(
                    ":",
                    1
                )

                playlist.extend([
                    f'#EXTINF:-1 tvg-logo="https://images.mlssoccer.com/image/private/t_editorial_landscape_8_desktop_mobile/mls/gxw8xgtyy9x6ukgyrdny.png" group-title="⚽⚽⚽|TV WORLDCUP 2026",{channel_id.upper()}',
                    f'#EXTVLCOPT:http-user-agent={UA}',
                    '#KODIPROP:inputstream.adaptive.license_type=clearkey',
                    f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}',
                    mpd_url
                ])

                total_ok += 1

                print(
                    f"      ✅ {channel_id} -> {player_name}"
                )

            except Exception as e:

                print(
                    f"      ❌ {channel_id}: {e}"
                )

        print(
            f"\n✅ Playlist 3 selesai ({total_ok} channel)"
        )

        return playlist

    except Exception as e:

        print(
            f"[!] Playlist 3 gagal: {e}"
        )

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
# PLAYLIST 2
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

playlist2_lines = []

for line in modified_playlist2.splitlines():

    if line.strip().startswith("#EXTM3U"):
        continue

    playlist2_lines.append(line)


# ===============================
# PLAYLIST 3
# ===============================
playlist3_lines = get_playlist3()


# ===============================
# GABUNGKAN OUTPUT
# ===============================
final_output = []

final_output.append("#EXTM3U")
final_output.append("")

# Playlist 1
final_output.extend(output1)

# Playlist 2
if playlist2_lines:
    final_output.append("")
    final_output.extend(playlist2_lines)

# Playlist 3
if playlist3_lines:
    final_output.append("")
    final_output.extend(playlist3_lines)


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
