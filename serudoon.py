import requests
import random
import time
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Konstanta path
MAPPING_FILE = Path.home() / "cool_mapping.txt"
CACHE_FILE = Path("proxy_cache.txt")
FAILED_FILE = Path("proxy_failed.txt")


# ===============================
# PARSE MAPPING (SUPPORT MULTI STREAM)
# ===============================
def parse_mapping_file(path):
    headers, mapping, default, constants = {}, {}, {}, {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("HEADERS."):
                k, v = line.split("=", 1)
                headers[k.split("HEADERS.")[1]] = v

            elif line.startswith("default."):
                k, v = line.split("=", 1)
                default[k.split("default.")[1]] = v

            elif any(x in line for x in [
                ".type", ".url", ".license",
                ".user-agent", ".referer", ".license_type"
            ]):
                k, v = line.split("=", 1)
                if "." in k:
                    id_part, prop = k.split(".", 1)

                    id_part = id_part.strip()
                    prop = prop.strip()
                    v = v.strip()

                    mapping.setdefault(id_part, [])

                    # bikin entry baru kalau belum ada atau ketemu type baru
                    if not mapping[id_part] or prop == "type":
                        mapping[id_part].append({})

                    mapping[id_part][-1][prop] = v

            elif "=" in line:
                k, v = line.split("=", 1)
                constants[k.strip()] = v.strip()

    return headers, constants, mapping, default


# ===============================
# PROXY
# ===============================
def get_proxy_list(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.text.strip().splitlines()
    except Exception as e:
        print(f"[!] Gagal ambil proxy list: {e}", file=sys.stderr)
        return []


def try_proxy(api_url, proxy, headers):
    proxies = {"http": proxy, "https": proxy}
    try:
        print(f"[•] Mencoba proxy: {proxy}", file=sys.stderr)
        res = requests.get(api_url, headers=headers, proxies=proxies, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[×] Proxy gagal: {proxy} → {e}", file=sys.stderr)
        return None


def simpan_cache_berhasil(proxy):
    CACHE_FILE.write_text(proxy)
    print(f"[✓] Proxy disimpan ke cache: {proxy}", file=sys.stderr)


def simpan_cache_gagal(proxy):
    with FAILED_FILE.open("a") as f:
        f.write(proxy + "\n")


# ===============================
# OUTPUT PLAYLIST (MULTI STREAM)
# ===============================
def tampilkan_playlist(data, constants, mapping, default):
    print("#EXTM3U")

    for item in data.get("included", []):
        if not isinstance(item, dict):
            continue

        attr = item.get("attributes", {})
        meta = item.get("links", {}).get("self", {}).get("meta", {})

        title = attr.get("title", "").strip().replace(":", "")
        logo = attr.get("cover_url", "").strip()
        start_time = attr.get("start_time")

        livestreaming_id = str(
            meta.get("livestreaming_id") or attr.get("content_id") or item.get("id") or ""
        ).strip()

        if not livestreaming_id or not start_time:
            continue

        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            waktu = dt.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m-%H.%M")
        except Exception:
            waktu = "JADWAL"

        # =============================
        # USER-AGENT PRIORITY
        # =============================
        ua = default.get("user-agent")
        ref = None

        if livestreaming_id in mapping:
            first_stream = mapping[livestreaming_id][0]
            ua = first_stream.get("user-agent") or ua
            ref = first_stream.get("referer")

        # =============================
        # MULTI STREAM OUTPUT
        # =============================
        if livestreaming_id in mapping:
            streams = mapping[livestreaming_id]

            for stream in streams:
                license_type = stream.get("license_type", "com.widevine.alpha")
                license_key = stream.get("license", "").replace("{id}", livestreaming_id)
                stream_url = stream.get("url", "").replace("{id}", livestreaming_id)
                manifest_type = "dash" if stream.get("type") == "dash" else "hls"

                label = f" [{manifest_type.upper()}]" if len(streams) > 1 else ""

                print(f'#EXTINF:-1 tvg-logo="{logo}" group-title="⚽️| LIVE EVENT",{waktu} {title}{label}')

                if ua:
                    print(f'#EXTVLCOPT:http-user-agent={ua}')
                if ref:
                    print(f'#EXTVLCOPT:http-referrer={ref}')

                print(f'#KODIPROP:inputstream.adaptive.manifest_type={manifest_type}')
                print(f'#KODIPROP:inputstream.adaptive.license_type={license_type}')
                print(f'#KODIPROP:inputstream.adaptive.license_key={license_key}')
                print(stream_url)
                print()

        else:
            # fallback default
            license_key = default.get("license", "").replace("{id}", livestreaming_id)
            dash_url = default.get("url", "").replace("{id}", livestreaming_id)

            print(f'#EXTINF:-1 tvg-logo="{logo}" group-title="⚽️| LIVE EVENT",{waktu} {title}')
            print('#KODIPROP:inputstreamaddon=inputstream.adaptive')
            print('#KODIPROP:inputstream.adaptive.manifest_type=dash')
            print('#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha')
            print(f'#KODIPROP:inputstream.adaptive.license_key={license_key}')
            print(dash_url)
            print()


# ===============================
# MAIN
# ===============================
def main():
    headers, constants, mapping, default = parse_mapping_file(MAPPING_FILE)
    proxy_url = constants.get("PROXY_LIST_URL")
    api_url = constants.get("URL")

    if not proxy_url or not api_url:
        print("❌ PROXY_LIST_URL atau URL tidak ditemukan dalam mapping.", file=sys.stderr)
        return 1

    proxies = get_proxy_list(proxy_url)
    random.shuffle(proxies)
    tried = set()

    if CACHE_FILE.exists():
        cached = CACHE_FILE.read_text().strip()
        if cached:
            data = try_proxy(api_url, cached, headers)
            if data:
                tampilkan_playlist(data, constants, mapping, default)
                print("[✓] Playlist diambil dari cache.", file=sys.stderr)
                return 0
            simpan_cache_gagal(cached)
            tried.add(cached)

    for proxy in proxies:
        if proxy in tried:
            continue

        data = try_proxy(api_url, proxy, headers)

        if data:
            simpan_cache_berhasil(proxy)
            tampilkan_playlist(data, constants, mapping, default)
            return 0

        simpan_cache_gagal(proxy)
        tried.add(proxy)
        time.sleep(1)

    print("❌ Semua proxy gagal.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
