import requests
import random
import time
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================================
# KONFIGURASI
# ============================================================
MAPPING_FILE = Path.home() / "cool_mapping.txt"
CACHE_FILE = Path("proxy_cache.txt")
FAILED_FILE = Path("proxy_failed.txt")

TIMEOUT = 15
WIB = timezone(timedelta(hours=7))


# ============================================================
# PARSE COOL MAPPING
# ============================================================
def parse_mapping_file(path):
    headers = {}
    constants = {}
    mapping = {}
    default = {}

    if not path.exists():
        raise FileNotFoundError(f"Mapping tidak ditemukan: {path}")

    properties = {
        "type", "url", "license",
        "user-agent", "referer", "license_type",
    }

    with path.open("r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key.startswith("HEADERS."):
                headers[key[len("HEADERS."):]] = value
                continue

            if key.startswith("default."):
                default[key[len("default."):]] = value
                continue

            if "." in key:
                id_part, prop = key.split(".", 1)
                id_part = id_part.strip()
                prop = prop.strip()

                if id_part.isdigit() and prop in properties:
                    streams = mapping.setdefault(id_part, [])
                    if prop == "type":
                        streams.append({"type": value.lower()})
                    else:
                        if not streams:
                            streams.append({})
                        streams[-1][prop] = value
                    continue

            constants[key] = value

    for stream_id in list(mapping):
        mapping[stream_id] = [
            s for s in mapping[stream_id]
            if s.get("type") or s.get("url")
        ]

    print(f"[✓] Mapping dimuat: {len(mapping)} ID", file=sys.stderr)
    return headers, constants, mapping, default


# ============================================================
# NORMALISASI MANIFEST
# ============================================================
def normalize_type(stream_type, url=""):
    stream_type = (stream_type or "").strip().lower()
    url = (url or "").strip().lower()

    if ".mpd" in url:
        return "dash"
    if ".m3u8" in url:
        return "hls"
    if stream_type in ("dash", "mpd", "mpeg-dash"):
        return "dash"
    if stream_type in ("hls", "m3u8"):
        return "hls"
    return ""


def replace_id(value, stream_id):
    return (value or "").replace("{id}", str(stream_id))


# ============================================================
# PROXY
# ============================================================
def get_proxy_list(url):
    if not url:
        print("[i] PROXY_LIST_URL tidak disetel; mencoba request langsung.",
              file=sys.stderr)
        return []

    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        proxies = [
            line.strip() for line in response.text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        print(f"[✓] Jumlah proxy: {len(proxies)}", file=sys.stderr)
        return proxies
    except requests.RequestException as exc:
        print(f"[!] Gagal mengambil daftar proxy: {exc}", file=sys.stderr)
        return []


def try_proxy(api_url, proxy, headers):
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    try:
        if proxy:
            print("[•] Menguji proxy...", file=sys.stderr)
        else:
            print("[•] Mencoba request langsung...", file=sys.stderr)

        response = requests.get(
            api_url, headers=headers, proxies=proxies, timeout=TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Respons API bukan objek JSON")

        print(f"[✓] API berhasil: HTTP {response.status_code}", file=sys.stderr)
        return data
    except (requests.RequestException, ValueError) as exc:
        print(f"[×] Request gagal: {exc}", file=sys.stderr)
        return None


def simpan_cache_berhasil(proxy):
    if not proxy:
        return
    CACHE_FILE.write_text(proxy, encoding="utf-8")
    print("[✓] Proxy disimpan ke cache.", file=sys.stderr)


def simpan_cache_gagal(proxy):
    if not proxy:
        return
    with FAILED_FILE.open("a", encoding="utf-8") as f:
        f.write(proxy + "\n")


# ============================================================
# OUTPUT SATU STREAM (fungsi tunggal, signature seragam)
# ============================================================
def emit_stream(f, title, logo, group, stream, stream_id=None, default=None):
    default = default or {}

    stream_url = replace_id(stream.get("url", ""), stream_id).strip()
    if not stream_url:
        print(f"[!] URL kosong: {stream_id}", file=sys.stderr)
        return False

    manifest_type = normalize_type(stream.get("type", ""), stream_url)
    if manifest_type not in ("hls", "dash"):
        print(f"[!] Tipe manifest tidak diketahui: {stream_id}",
              file=sys.stderr)
        return False

    ua = stream.get("user-agent") or default.get("user-agent") or ""
    ref = stream.get("referer") or default.get("referer") or ""

    label = manifest_type.upper()

    f.write(
        f'#EXTINF:-1 tvg-logo="{logo}" '
        f'group-title="{group}",{title} [{label}]\n'
    )

    if ua:
        f.write(f"#EXTVLCOPT:http-user-agent={ua}\n")

    # --------------------------------------------------------
    # HLS: hanya manifest_type=hls + URL (tanpa addon/license)
    # --------------------------------------------------------
    if manifest_type == "hls":
        f.write("#KODIPROP:inputstream.adaptive.manifest_type=hls\n")
        if ref:
            f.write(f"#EXTVLCOPT:http-referrer={ref}\n")
        f.write(stream_url + "\n\n")
        print(f"[✓] {stream_id} -> HLS", file=sys.stderr)
        return True

    # --------------------------------------------------------
    # DASH: full inputstream + DRM
    # --------------------------------------------------------
    license_type = (
        stream.get("license_type")
        or default.get("license_type")
        or "com.widevine.alpha"
    )
    license_key = replace_id(
        stream.get("license") or default.get("license", ""),
        stream_id,
    )

    f.write("#KODIPROP:inputstreamaddon=inputstream.adaptive\n")
    f.write("#KODIPROP:inputstream.adaptive.manifest_type=mpd\n")

    if license_type:
        f.write(f"#KODIPROP:inputstream.adaptive.license_type={license_type}\n")
    if license_key:
        f.write(f"#KODIPROP:inputstream.adaptive.license_key={license_key}\n")
    if ref:
        f.write(f"#EXTVLCOPT:http-referrer={ref}\n")

    f.write(stream_url + "\n\n")
    print(f"[✓] {stream_id} -> DASH", file=sys.stderr)
    return True


# ============================================================
# MEMBENTUK KONFIGURASI STREAM DEFAULT MPD
# ============================================================
def build_default_dash(stream_id, default):
    url = replace_id(default.get("url", ""), stream_id)
    if not url:
        return None

    manifest_type = normalize_type(default.get("type") or "dash", url)
    if manifest_type != "dash":
        return None

    return {
        "type": "dash",
        "url": url,
        "license": default.get("license", ""),
        "license_type": default.get("license_type") or "com.widevine.alpha",
        "user-agent": default.get("user-agent", ""),
        "referer": default.get("referer", ""),
    }


# ============================================================
# EKSTRAK EVENT DARI RESPON API
# ============================================================
def extract_events(data):
    """
    Cari list event dari respons API.
    Respons biasanya: {"included": [ {attributes, links, id}, ... ]}
    atau {"data": [...]}.
    """
    if not isinstance(data, dict):
        return []

    for key in ("included", "data", "results", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    # Fallback: cari list pertama yang isinya dict dengan attributes
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    return []


# ============================================================
# PROSES EVENT DAN PEMBUATAN PLAYLIST
# ============================================================
def process_events(f, included, mapping, default, group):
    total_events = 0
    total_hls = 0
    total_dash = 0

    for item in included:
        if not isinstance(item, dict):
            continue

        attr = item.get("attributes") or {}
        links = item.get("links") or {}
        self_link = links.get("self") or {}
        meta = self_link.get("meta") or {}

        title = str(attr.get("title") or "").strip().replace(":", "")
        logo = str(attr.get("cover_url") or "").strip()
        start_time = attr.get("start_time")

        stream_id = str(
            meta.get("livestreaming_id")
            or attr.get("content_id")
            or item.get("id")
            or ""
        ).strip()

        if not stream_id or not start_time:
            continue

        try:
            dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
            waktu = dt.astimezone(WIB).strftime("%d/%m-%H.%M")
        except (ValueError, TypeError):
            waktu = "JADWAL"

        display_title = f"{waktu} {title}".strip()

        streams = mapping.get(stream_id, [])

        # ----------------------------------------------------
        # ID MEMILIKI MAPPING KHUSUS
        # ----------------------------------------------------
        if streams:
            total_events += 1

            for stream in streams:
                stream_type = normalize_type(
                    stream.get("type", ""), stream.get("url", "")
                )
                success = emit_stream(
                    f=f,
                    title=display_title,
                    logo=logo,
                    group=group,
                    stream=stream,
                    stream_id=stream_id,
                    default=default,
                )
                if success:
                    if stream_type == "dash":
                        total_dash += 1
                    elif stream_type == "hls":
                        total_hls += 1
            continue

        # ----------------------------------------------------
        # ID TANPA MAPPING KHUSUS: DASH DEFAULT
        # ----------------------------------------------------
        default_dash = build_default_dash(stream_id, default)
        if not default_dash:
            print(f"[!] Tidak ada URL MPD default untuk ID {stream_id}",
                  file=sys.stderr)
            continue

        if emit_stream(
            f=f,
            title=display_title,
            logo=logo,
            group=group,
            stream=default_dash,
            stream_id=stream_id,
            default=default,
        ):
            total_events += 1
            total_dash += 1

    print(
        "[✓] Selesai: "
        f"{total_events} event diproses, "
        f"{total_dash} stream DASH, "
        f"{total_hls} stream HLS.",
        file=sys.stderr,
    )


# ============================================================
# TAMPILKAN PLAYLIST
# ============================================================
def tampilkan_playlist(data, constants, mapping, default):
    group = constants.get("GROUP_TITLE", "⚽️| LIVE EVENT")
    output_file = Path(constants.get("OUTPUT_FILE", "playlist.m3u"))

    events = extract_events(data)

    with output_file.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        process_events(f, events, mapping, default, group)

    print(f"[✓] Playlist ditulis ke: {output_file}", file=sys.stderr)


# ============================================================
# MAIN
# ============================================================
def main():
    try:
        headers, constants, mapping, default = parse_mapping_file(MAPPING_FILE)
    except Exception as exc:
        print(f"[!] Gagal membaca mapping: {exc}", file=sys.stderr)
        return 1

    api_url = constants.get("URL")
    proxy_url = constants.get("PROXY_LIST_URL")

    if not api_url:
        print("[!] URL API tidak ditemukan di cool_mapping.txt.", file=sys.stderr)
        return 1

    proxies = get_proxy_list(proxy_url)
    random.shuffle(proxies)
    tried = set()

    if CACHE_FILE.exists():
        cached = CACHE_FILE.read_text(encoding="utf-8").strip()
        if cached:
            data = try_proxy(api_url, cached, headers)
            if data is not None:
                simpan_cache_berhasil(cached)
                tampilkan_playlist(data, constants, mapping, default)
                print("[✓] Playlist menggunakan proxy cache.", file=sys.stderr)
                return 0
            simpan_cache_gagal(cached)
            tried.add(cached)

    for proxy in proxies:
        if proxy in tried:
            continue
        data = try_proxy(api_url, proxy, headers)
        if data is not None:
            simpan_cache_berhasil(proxy)
            tampilkan_playlist(data, constants, mapping, default)
            return 0
        simpan_cache_gagal(proxy)
        tried.add(proxy)
        time.sleep(1)

    print("[i] Mencoba API tanpa proxy...", file=sys.stderr)
    data = try_proxy(api_url, None, headers)
    if data is not None:
        tampilkan_playlist(data, constants, mapping, default)
        return 0

    print("[×] Semua percobaan request gagal.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
