import requests
import random
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
PROXY_LIST_URL = config_vars.get("PROXY_LIST_URL")

if not API_URL:
    print("[!] API_URL tidak ditemukan di config")
    sys.exit()

if not API_URL2:
    print("[!] API_URL2 tidak ditemukan di config")
    sys.exit()

if not PROXY_LIST_URL:
    print("[!] PROXY_LIST_URL tidak ditemukan di config")
    sys.exit()

# ===============================
# AMBIL LIST PROXY
# ===============================
def get_proxy_list(url):
    try:
        print("[*] Mengambil proxy list...")

        res = requests.get(url, timeout=15)
        res.raise_for_status()

        proxies = res.text.strip().splitlines()

        print(f"[✓] Total proxy: {len(proxies)}")

        return proxies

    except Exception as e:
        print(f"[!] Gagal ambil proxy list: {e}")
        return []


# ===============================
# FETCH PLAYLIST VIA PROXY
# ===============================
def fetch_with_proxy(url, proxies_list):

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for proxy in proxies_list:

        proxy = proxy.strip()

        if not proxy:
            continue

        if not proxy.startswith("http"):
            proxy = "http://" + proxy

        proxies = {
            "http": proxy,
            "https": proxy
        }

        try:
            print(f"[+] Coba proxy: {proxy}")

            res = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=20,
                verify=False,
                allow_redirects=True
            )

            # validasi playlist
            if (
                res.status_code == 200
                and "#EXTM3U" in res.text
            ):

                print(f"[✓] Berhasil pakai proxy: {proxy}")

                return res.text

            else:
                print(f"[x] Bukan playlist valid")

        except Exception as e:
            print(f"[x] Proxy gagal: {proxy} -> {e}")

    return None


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
# AMBIL PROXY
# ===============================
proxy_list = get_proxy_list(PROXY_LIST_URL)

if not proxy_list:
    print("[!] Proxy kosong")
    sys.exit()

random.shuffle(proxy_list)

# ===============================
# PLAYLIST 1 (FILTER CH CUBMU)
# ===============================
print("\n▶️ Mengambil playlist 1...")

playlist_text = fetch_with_proxy(API_URL, proxy_list)

if not playlist_text:
    print("[!] Semua proxy gagal untuk playlist 1")
    sys.exit()

lines = playlist_text.splitlines()

output1 = []

i = 0

while i < len(lines):

    line = lines[i].strip()

    # filter CH CUBMU
    if (
        line.startswith("#EXTINF")
        and 'group-title="CH CUBMU"' in line
    ):

        # ubah group-title
        line = line.replace(
            'group-title="CH CUBMU"',
            'group-title="🧧|CH CUBMU"'
        )

        output1.append(line)

        j = i + 1

        while j < len(lines):

            next_line = lines[j].strip()

            # stop jika channel baru
            if next_line.startswith("#EXTINF"):
                break

            if next_line:
                output1.append(next_line)

            # stop jika URL stream
            if next_line.startswith("http"):
                break

            j += 1

        output1.append("")

        i = j

    i += 1

# ===============================
# PLAYLIST 2 (SEMUA GROUP DIGANTI)
# ===============================
print("\n▶️ Mengambil playlist 2...")

playlist2_text = fetch_with_proxy(API_URL2, proxy_list)

if not playlist2_text:
    print("[!] Semua proxy gagal untuk playlist 2")
    sys.exit()

print("▶️ Mengganti semua group-title playlist 2...")

modified_playlist2 = replace_group_title(
    playlist2_text,
    "🧧|CH CUBMU2"
)

# ===============================
# GABUNGKAN OUTPUT
# ===============================
final_output = []

# header
final_output.append("#EXTM3U")
final_output.append("")

# playlist 1
final_output.extend(output1)

# playlist 2
final_output.append("")
final_output.append(modified_playlist2)

# ===============================
# SIMPAN FILE
# ===============================
OUTPUT_FILE = "ZIGZAGO.m3u"

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(final_output))

print(f"\n✅ Berhasil simpan {OUTPUT_FILE}")
