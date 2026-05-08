import requests
import random
import sys
import urllib3
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
PROXY_LIST_URL = config_vars.get("PROXY_LIST_URL")

if not API_URL:
    print("[!] API_URL tidak ditemukan di config")
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
# AMBIL PROXY
# ===============================
proxy_list = get_proxy_list(PROXY_LIST_URL)

if not proxy_list:
    print("[!] Proxy kosong")
    sys.exit()

random.shuffle(proxy_list)

# ===============================
# AMBIL PLAYLIST
# ===============================
playlist_text = fetch_with_proxy(API_URL, proxy_list)

if not playlist_text:
    print("[!] Semua proxy gagal")
    sys.exit()

# ===============================
# PARSE PLAYLIST
# ===============================
lines = playlist_text.splitlines()

output = []

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

        output.append(line)

        j = i + 1

        while j < len(lines):

            next_line = lines[j].strip()

            # stop jika channel baru
            if next_line.startswith("#EXTINF"):
                break

            if next_line:
                output.append(next_line)

            # stop jika URL stream
            if next_line.startswith("http"):
                break

            j += 1

        output.append("")

        i = j

    i += 1


# ===============================
# SIMPAN FILE
# ===============================
OUTPUT_FILE = "ZIGZAGO.m3u"

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(output))

print(f"✅ Berhasil simpan {OUTPUT_FILE}")
