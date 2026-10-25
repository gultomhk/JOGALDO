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
        raise FileNotFoundError(
            f"Mapping tidak ditemukan: {path}"
        )

    properties = {
        "type",
        "url",
        "license",
        "user-agent",
        "referer",
        "license_type",
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

            # Header global
            if key.startswith("HEADERS."):
                headers[key[len("HEADERS."):]] = value
                continue

            # Konfigurasi default
            if key.startswith("default."):
                default[key[len("default."):]] = value
                continue

            # Konfigurasi per ID
            if "." in key:
                id_part, prop = key.split(".", 1)
                id_part = id_part.strip()
                prop = prop.strip()

                if id_part.isdigit() and prop in properties:
                    streams = mapping.setdefault(id_part, [])

                    # Setiap type baru adalah stream baru.
                    if prop == "type":
                        streams.append({
                            "type": value.lower()
                        })
                    else:
                        if not streams:
                            streams.append({})

                        streams[-1][prop] = value

                    continue

            # Konstanta umum seperti URL dan PROXY_LIST_URL
            constants[key] = value

    # Hapus entry kosong.
    for stream_id in list(mapping):
        mapping[stream_id] = [
            stream for stream in mapping[stream_id]
            if stream.get("type") or stream.get("url")
        ]

    print(
        f"[✓] Mapping dimuat: {len(mapping)} ID",
        file=sys.stderr
    )

    return headers, constants, mapping, default


# ============================================================
# NORMALISASI MANIFEST
# ============================================================
def normalize_type(stream_type, url=""):
    stream_type = (stream_type or "").strip().lower()
    url = (url or "").strip().lower()

    # Periksa ekstensi URL terlebih dahulu.
    # URL .mpd harus diperlakukan sebagai DASH.
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
        print(
            "[i] PROXY_LIST_URL tidak disetel; "
            "akan mencoba request langsung.",
            file=sys.stderr
        )
        return []

    try:
        response = requests.get(
            url,
            timeout=TIMEOUT
        )
        response.raise_for_status()

        proxies = [
            line.strip()
            for line in response.text.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
        ]

        print(
            f"[✓] Jumlah proxy: {len(proxies)}",
            file=sys.stderr
        )

        return proxies

    except requests.RequestException as exc:
        print(
            f"[!] Gagal mengambil daftar proxy: {exc}",
            file=sys.stderr
        )
        return []


def try_proxy(api_url, proxy, headers):
    proxies = None

    if proxy:
        proxies = {
            "http": proxy,
            "https": proxy,
        }

    try:
        if proxy:
            print(
                "[•] Menguji proxy...",
                file=sys.stderr
            )
        else:
            print(
                "[•] Mencoba request langsung...",
                file=sys.stderr
            )

        response = requests.get(
            api_url,
            headers=headers,
            proxies=proxies,
            timeout=TIMEOUT,
        )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                "Respons API bukan objek JSON"
            )

        print(
            f"[✓] API berhasil: HTTP {response.status_code}",
            file=sys.stderr
        )

        return data

    except (
        requests.RequestException,
        ValueError,
    ) as exc:
        print(
            f"[×] Request gagal: {exc}",
            file=sys.stderr
        )
        return None


def simpan_cache_berhasil(proxy):
    if not proxy:
        return

    CACHE_FILE.write_text(
        proxy,
        encoding="utf-8"
    )

    print(
        "[✓] Proxy disimpan ke cache.",
        file=sys.stderr
    )


def simpan_cache_gagal(proxy):
    if not proxy:
        return

    with FAILED_FILE.open(
        "a",
        encoding="utf-8"
    ) as f:
        f.write(proxy + "\n")


# ============================================================
# OUTPUT SATU STREAM
# ============================================================
def emit_stream(
    title,
    logo,
    waktu,
    stream_id,
    stream,
    default,
):
    stream_url = replace_id(
        stream.get("url", ""),
        stream_id,
    )

    manifest_type = normalize_type(
        stream.get("type"),
        stream_url,
    )

    if not manifest_type:
        print(
            f"[!] Tipe manifest tidak diketahui: {stream_id}",
            file=sys.stderr
        )
        return False

    if not stream_url:
        print(
            f"[!] URL kosong: {stream_id}",
            file=sys.stderr
        )
        return False

    # Header khusus stream lebih diutamakan.
    ua = (
        stream.get("user-agent")
        or default.get("user-agent")
    )

    ref = (
        stream.get("referer")
        or default.get("referer")
    )

    # Lisensi khusus stream lebih diutamakan.
    license_type = (
        stream.get("license_type")
        or default.get("license_type")
        or "com.widevine.alpha"
    )

    license_key = replace_id(
        stream.get("license")
        or default.get("license", ""),
        stream_id,
    )

    # Label selalu ditampilkan supaya MPD dan HLS
    # mudah dibedakan dalam playlist.
    label = manifest_type.upper()

    print(
        f'#EXTINF:-1 tvg-logo="{logo}" '
        f'group-title="⚽️| LIVE EVENT",'
        f'{waktu} {title} [{label}]'
    )

    if ua:
        print(
            f"#EXTVLCOPT:http-user-agent={ua}"
        )

    if ref:
        print(
            f"#EXTVLCOPT:http-referrer={ref}"
        )

    print(
        "#KODIPROP:inputstreamaddon=inputstream.adaptive"
    )

    print(
        "#KODIPROP:inputstream.adaptive.manifest_type="
        f"{manifest_type}"
    )

    # License hanya ditulis jika tersedia.
    if license_type:
        print(
            "#KODIPROP:inputstream.adaptive.license_type="
            f"{license_type}"
        )

    if license_key:
        print(
            "#KODIPROP:inputstream.adaptive.license_key="
            f"{license_key}"
        )

    print(stream_url)
    print()

    print(
        f"[✓] {stream_id} -> {manifest_type.upper()}",
        file=sys.stderr
    )

    return True


# ============================================================
# MEMBENTUK KONFIGURASI STREAM DEFAULT MPD
# ============================================================
def build_default_dash(stream_id, default):
    url = replace_id(
        default.get("url", ""),
        stream_id,
    )

    if not url:
        return None

    # Jangan menghasilkan MPD jika URL default
    # ternyata URL HLS.
    manifest_type = normalize_type(
        default.get("type") or "dash",
        url,
    )

    if manifest_type != "dash":
        return None

    return {
        "type": "dash",
        "url": url,
        "license": default.get("license", ""),
        "license_type": (
            default.get("license_type")
            or "com.widevine.alpha"
        ),
        "user-agent": default.get("user-agent", ""),
        "referer": default.get("referer", ""),
    }



# ============================================================
# OUTPUT STREAM M3U
# ============================================================
def emit_stream(f, title, logo, group, stream, stream_id=None):
    url = str(stream.get("url") or "").strip()

    if not url:
        return False

    stream_type = normalize_type(
        stream.get("type", ""),
        url
    )

    # Hindari tipe kosong atau tidak dikenal.
    if stream_type not in ("hls", "dash"):
        print(
            f"[!] Tipe stream tidak dikenal untuk ID "
            f"{stream_id or '-'}: {stream_type}",
            file=sys.stderr
        )
        return False

    f.write(
        f'#EXTINF:-1 tvg-logo="{logo}" '
        f'group-title="{group}",{title} [{stream_type.upper()}]\n'
    )

    user_agent = str(
        stream.get("user-agent") or ""
    ).strip()

    referer = str(
        stream.get("referer") or ""
    ).strip()

    if user_agent:
        f.write(
            f"#EXTVLCOPT:http-user-agent={user_agent}\n"
        )

    # --------------------------------------------------------
    # HLS: hanya User-Agent dan URL.
    # Tidak menambahkan KODIPROP atau lisensi.
    # --------------------------------------------------------
    if stream_type == "hls":
        f.write(url + "\n")
        return True

    # --------------------------------------------------------
    # DASH: konfigurasi inputstream dan DRM.
    # --------------------------------------------------------
    f.write(
        "#KODIPROP:inputstreamaddon=inputstream.adaptive\n"
    )
    f.write(
        "#KODIPROP:inputstream.adaptive.manifest_type=mpd\n"
    )

    license_type = str(
        stream.get("license_type") or ""
    ).strip()

    license_key = str(
        stream.get("license") or ""
    ).strip()

    if license_type:
        f.write(
            "#KODIPROP:inputstream.adaptive.license_type="
            f"{license_type}\n"
        )

    if license_key:
        f.write(
            "#KODIPROP:inputstream.adaptive.license_key="
            f"{license_key}\n"
        )

    if referer:
        f.write(
            f"#EXTVLCOPT:http-referrer={referer}\n"
        )

    f.write(url + "\n")
    return True


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

        title = str(
            attr.get("title") or ""
        ).strip().replace(":", "")

        logo = str(
            attr.get("cover_url") or ""
        ).strip()

        start_time = attr.get("start_time")

        stream_id = str(
            meta.get("livestreaming_id")
            or attr.get("content_id")
            or item.get("id")
            or ""
        ).strip()

        if not stream_id or not start_time:
            continue

        # ----------------------------------------------------
        # FORMAT WAKTU WIB
        # ----------------------------------------------------
        try:
            dt = datetime.fromisoformat(
                str(start_time).replace("Z", "+00:00")
            )

            waktu = dt.astimezone(WIB).strftime(
                "%d/%m-%H.%M"
            )

        except (ValueError, TypeError):
            waktu = "JADWAL"

        # Gabungkan waktu ke judul agar sesuai output sebelumnya.
        display_title = f"{waktu} {title}".strip()

        streams = mapping.get(stream_id, [])

        # ----------------------------------------------------
        # ID MEMILIKI MAPPING KHUSUS
        # ----------------------------------------------------
        if streams:
            has_dash = False
            has_hls = False

            # Deteksi tipe berdasarkan mapping dan URL.
            for stream in streams:
                stream_type = normalize_type(
                    stream.get("type", ""),
                    stream.get("url", "")
                )

                if stream_type == "dash":
                    has_dash = True
                elif stream_type == "hls":
                    has_hls = True

            # Hitung event satu kali.
            total_events += 1

            # Tulis semua stream mapping.
            for stream in streams:
                stream_type = normalize_type(
                    stream.get("type", ""),
                    stream.get("url", "")
                )

                success = emit_stream(
                    f=f,
                    title=display_title,
                    logo=logo,
                    group=group,
                    stream=stream,
                    stream_id=stream_id
                )

                if success:
                    if stream_type == "dash":
                        total_dash += 1
                    elif stream_type == "hls":
                        total_hls += 1

            # ------------------------------------------------
            # MAPPING HLS TANPA DASH:
            # Tambahkan DASH default bila tersedia.
            # ------------------------------------------------
            if has_hls and not has_dash:
                default_dash = build_default_dash(
                    stream_id,
                    default
                )

                if default_dash:
                    print(
                        f"[+] Menambahkan MPD default "
                        f"untuk ID {stream_id}",
                        file=sys.stderr
                    )

                    if emit_stream(
                        f=f,
                        title=display_title,
                        logo=logo,
                        group=group,
                        stream=default_dash,
                        stream_id=stream_id
                    ):
                        total_dash += 1

                else:
                    print(
                        f"[!] ID {stream_id} memiliki HLS, "
                        "tetapi URL MPD default tidak tersedia.",
                        file=sys.stderr
                    )

            continue

        # ----------------------------------------------------
        # ID TANPA MAPPING KHUSUS: DASH DEFAULT
        # ----------------------------------------------------
        default_dash = build_default_dash(
            stream_id,
            default
        )

        if not default_dash:
            print(
                f"[!] Tidak ada URL MPD default "
                f"untuk ID {stream_id}",
                file=sys.stderr
            )
            continue

        if emit_stream(
            f=f,
            title=display_title,
            logo=logo,
            group=group,
            stream=default_dash,
            stream_id=stream_id
        ):
            total_events += 1
            total_dash += 1

    print(
        "[✓] Selesai: "
        f"{total_events} event diproses, "
        f"{total_dash} stream DASH, "
        f"{total_hls} stream HLS.",
        file=sys.stderr
    )


# ============================================================
# MAIN
# ============================================================
def main():
    try:
        headers, constants, mapping, default = (
            parse_mapping_file(MAPPING_FILE)
        )

    except Exception as exc:
        print(
            f"[!] Gagal membaca mapping: {exc}",
            file=sys.stderr
        )
        return 1

    api_url = constants.get("URL")
    proxy_url = constants.get("PROXY_LIST_URL")

    if not api_url:
        print(
            "[!] URL API tidak ditemukan di cool_mapping.txt.",
            file=sys.stderr
        )
        return 1

    # Ambil daftar proxy jika dikonfigurasi.
    proxies = get_proxy_list(proxy_url)
    random.shuffle(proxies)

    # Cache hanya digunakan jika proxy tersedia.
    tried = set()

    if CACHE_FILE.exists():
        cached = CACHE_FILE.read_text(
            encoding="utf-8"
        ).strip()

        if cached:
            data = try_proxy(
                api_url,
                cached,
                headers,
            )

            if data is not None:
                simpan_cache_berhasil(cached)

                tampilkan_playlist(
                    data,
                    constants,
                    mapping,
                    default,
                )

                print(
                    "[✓] Playlist menggunakan proxy cache.",
                    file=sys.stderr
                )
                return 0

            simpan_cache_gagal(cached)
            tried.add(cached)

    # --------------------------------------------------------
    # COBA PROXY YANG TERSEDIA
    # --------------------------------------------------------
    for proxy in proxies:
        if proxy in tried:
            continue

        data = try_proxy(
            api_url,
            proxy,
            headers,
        )

        if data is not None:
            simpan_cache_berhasil(proxy)

            tampilkan_playlist(
                data,
                constants,
                mapping,
                default,
            )

            return 0

        simpan_cache_gagal(proxy)
        tried.add(proxy)
        time.sleep(1)

    # --------------------------------------------------------
    # FALLBACK REQUEST LANGSUNG
    # --------------------------------------------------------
    print(
        "[i] Mencoba API tanpa proxy...",
        file=sys.stderr
    )

    data = try_proxy(
        api_url,
        None,
        headers,
    )

    if data is not None:
        tampilkan_playlist(
            data,
            constants,
            mapping,
            default,
        )
        return 0

    print(
        "[×] Semua percobaan request gagal.",
        file=sys.stderr
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
