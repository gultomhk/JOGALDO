import requests
from datetime import datetime, timezone, timedelta
import random, time
from pathlib import Path
import sys

mapping_file = Path.home() / "cool_mapping.txt"
CACHE_FILE = Path("proxy_cache.txt")
FAILED_FILE = Path("proxy_failed.txt")


def parse_mapping_file(path):
    headers = {}
    mapping = {}
    default = {}
    constants = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("HEADERS."):
                key, value = line.split("=", 1)
                headers[key.split("HEADERS.")[1]] = value
            elif line.startswith("default."):
                key, value = line.split("=", 1)
                default[key.split("default.")[1]] = value
            elif "=" in line and not any(x in line for x in [".type", ".url", ".license"]):
                key, value = line.split("=", 1)
                constants[key.strip()] = value.strip()
            elif any(k in line for k in [".type", ".url"]):
                key, value = line.split("=", 1)
                id_part, prop = key.split(".")
                if id_part not in mapping:
                    mapping[id_part] = {}
                mapping[id_part][prop] = value

    return headers, constants, mapping, default


HEADERS, CONSTANTS, MAPPING, DEFAULT = parse_mapping_file(mapping_file)
PROXY_LIST_URL = CONSTANTS.get("PROXY_LIST_URL")
API_URL = CONSTANTS.get("URL")


def get_proxy_list():
    try:
        res = requests.get(PROXY_LIST_URL, timeout=10)
        res.raise_for_status()
        return res.text.strip().splitlines()
    except Exception as e:
        print(f"[!] Gagal ambil proxy list: {e}", file=sys.stderr)
        return []


def try_proxy(proxy):
    proxies = {"http": proxy, "https": proxy}
    try:
        print(f"[•] Coba proxy: {proxy}", file=sys.stderr)
        res = requests.get(API_URL, headers=HEADERS, proxies=proxies, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[×] Gagal dengan proxy {proxy}: {e}", file=sys.stderr)
        return None


def simpan_proxy_berhasil(proxy):
    CACHE_FILE.write_text(proxy)
    print(f"[✓] Proxy berhasil disimpan ke cache: {proxy}", file=sys.stderr)


def simpan_proxy_gagal(proxy):
    with open(FAILED_FILE, "a") as f:
        f.write(proxy + "\n")


def tampilkan_playlist(data):
    print("#EXTM3U")

    for item in data.get("included", []):
        attr = item.get("attributes", {})
        meta = item.get("links", {}).get("self", {}).get("meta", {})

        title = attr.get("title", "").replace(":", "")
        logo = attr.get("cover_url", "")
        start_time = attr.get("start_time")
        livestreaming_id = str(meta.get("livestreaming_id", "")).strip()

        if not livestreaming_id or not start_time:
            continue

        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        wib = dt.astimezone(timezone(timedelta(hours=7)))
        waktu = wib.strftime("%d/%m-%H.%M")

        print(f'#EXTINF:-1 tvg-logo="{logo}" group-title="⚽️| LIVE EVENT", {waktu} {title}')
        print('#EXTVLCOPT:http-user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/534.24 (KHTML, like Gecko) Chrome/11.0.696.34 Safari/534.24')

        if livestreaming_id in CONSTANTS:
            print(CONSTANTS[livestreaming_id])
        elif livestreaming_id in MAPPING and MAPPING[livestreaming_id].get("type") == "hls":
            print(MAPPING[livestreaming_id].get("url"))
        else:
            license_key = DEFAULT["license"].replace("{id}", livestreaming_id)
            dash_url = DEFAULT["url"].replace("{id}", livestreaming_id)
            print('#KODIPROP:inputstreamaddon=inputstream.adaptive')
            print('#KODIPROP:inputstream.adaptive.manifest_type=dash')
            print('#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha')
            print(f'#KODIPROP:inputstream.adaptive.license_key={license_key}')
            print(dash_url)

        print()  # Spasi antar entry


def main():
    proxies = get_proxy_list()
    random.shuffle(proxies)
    tried = set()

    if CACHE_FILE.exists():
        cached = CACHE_FILE.read_text().strip()
        if cached:
            print(f"[•] Coba proxy dari cache: {cached}", file=sys.stderr)
            data = try_proxy(cached)
            if data:
                tampilkan_playlist(data)
                print(f"[✓] Playlist disimpan ke stdout", file=sys.stderr)
                return 0
            simpan_proxy_gagal(cached)
            tried.add(cached)

    for proxy in proxies:
        if proxy in tried:
            continue
        data = try_proxy(proxy)
        if data:
            simpan_proxy_berhasil(proxy)
            tampilkan_playlist(data)
            print(f"[✓] Playlist disimpan ke stdout", file=sys.stderr)
            return 0
        simpan_proxy_gagal(proxy)
        tried.add(proxy)
        time.sleep(1)

    print("❌ Semua proxy gagal.", file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
