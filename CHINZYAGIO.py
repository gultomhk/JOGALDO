import requests
import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ==========================
# Load Config
# ==========================
CHINZYAIGODATA_FILE = Path.home() / "chinzyaigodata_file.txt"
config_vars = {}
with open(CHINZYAIGODATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URLS = config_vars.get("BASE_URLS", [])
PROXY_LIST_URL = config_vars.get("PROXY_LIST_URL")
DOMAIN_DRM = config_vars.get("DOMAIN_DRM", "")
DOMAIN_MPD = config_vars.get("DOMAIN_MPD", "")

LAST_PROXY_FILE = Path("last_proxy.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
    "Accept": "application/json, text/plain, */*"
}

TIMEZONE_OFFSET = timedelta(hours=7)  # WIB


# =============================
# PROXY FUNCTIONS
# =============================

def proxy_config(proxy_str: str):
    """Konversi string proxy jadi dict http/https"""
    if proxy_str.startswith("socks5://") or ":1080" in proxy_str:
        scheme = "socks5"
    elif proxy_str.startswith("socks4://"):
        scheme = "socks4"
    else:
        scheme = "http"
    proxy_clean = proxy_str.replace("socks5://", "").replace("socks4://", "")
    return {"http": f"{scheme}://{proxy_clean}", "https": f"{scheme}://{proxy_clean}"}


def load_proxies():
    """Unduh daftar proxy"""
    try:
        print("🌐 Mengunduh daftar proxy...")
        res = requests.get(PROXY_LIST_URL, timeout=10)
        res.raise_for_status()
        proxies = [p.strip() for p in res.text.splitlines() if p.strip()]
        print(f"✅ {len(proxies)} proxy ditemukan.")
        return proxies
    except Exception as e:
        print(f"⚠️ Gagal memuat proxy list: {e}")
        return []


def find_working_proxy(test_url, headers, proxy_list):
    """Cari satu proxy yang berhasil digunakan"""
    random.shuffle(proxy_list)
    for proxy in proxy_list:
        conf = proxy_config(proxy)
        try:
            print(f"🔌 Mencoba proxy: {conf['http']}")
            res = requests.get(test_url, headers=headers, proxies=conf, timeout=10)
            if res.status_code == 200:
                print(f"✅ Proxy sukses: {proxy}")
                LAST_PROXY_FILE.write_text(proxy, encoding="utf-8")
                return conf
        except Exception:
            print(f"❌ Proxy gagal: {proxy}")
    print("⚠️ Tidak ada proxy yang berhasil, lanjut tanpa proxy.")
    return None


def load_last_proxy():
    """Gunakan proxy sukses terakhir jika masih valid"""
    if LAST_PROXY_FILE.exists():
        proxy_str = LAST_PROXY_FILE.read_text(encoding="utf-8").strip()
        if proxy_str:
            conf = proxy_config(proxy_str)
            print(f"♻️ Menggunakan proxy sebelumnya: {proxy_str}")
            try:
                res = requests.get(BASE_URLS[0], headers=HEADERS, proxies=conf, timeout=10)
                if res.status_code == 200:
                    print("✅ Proxy lama masih berfungsi.")
                    return conf
                else:
                    print("⚠️ Proxy lama tidak valid, akan cari baru.")
            except Exception:
                print("⚠️ Proxy lama gagal, cari baru.")
    return None


# =============================
# FETCH & PARSE
# =============================

def fetch_matches():
    global_proxy = load_last_proxy()

    if not global_proxy:
        proxies = load_proxies()
        if proxies:
            global_proxy = find_working_proxy(BASE_URLS[0], HEADERS, proxies)

    matches = []
    for url in BASE_URLS:
        try:
            print(f"🔗 Fetching {url}")
            if global_proxy:
                res = requests.get(url, headers=HEADERS, proxies=global_proxy, timeout=15)
            else:
                res = requests.get(url, headers=HEADERS, timeout=15)

            res.raise_for_status()
            data = res.json()
            results = data.get("results") or data.get("items") or []

            for item in results:
                if "id" not in item:
                    continue

                id_ = item["id"]
                title = item.get("title") or item.get("standardTitle") or "Untitled"
                logo = (
                    item.get("wideCoverUrl")
                    or item.get("backdropUri")
                    or item.get("posterImage", {}).get("url", "")
                )

                start = item.get("startDate")
                if not start:
                    continue

                # Convert UTC -> WIB
                try:
                    dt_utc = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    dt_wib = dt_utc.astimezone(timezone(TIMEZONE_OFFSET))
                    date_str = dt_wib.strftime("%d/%m-%H.%M")
                except Exception:
                    date_str = "??/??-??.??"

                # Format judul rapi
                if "|" in title:
                    parts = title.split("|", 1)
                    match_name = parts[0].strip().replace(" v ", " vs ")
                    tournament = parts[1].strip()
                    formatted_title = f"{match_name} ({tournament})"
                else:
                    formatted_title = title.strip().replace(" v ", " vs ")

                matches.append({
                    "id": id_,
                    "title": f"{date_str} {formatted_title}",
                    "logo": logo
                })
        except Exception as e:
            print(f"⚠️ Error fetching {url}: {e}")

    return matches


# =============================
# BUILD M3U
# =============================

def build_m3u(matches):
    lines = ["#EXTM3U"]
    for m in matches:
        lines.append(f'#EXTINF:-1 tvg-logo="{m["logo"]}" group-title="⚽️| LIVE EVENT",{m["title"]}')
        lines.append("#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0")
        lines.append("#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha")
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={DOMAIN_DRM}{m["id"]}')
        lines.append(f'{DOMAIN_MPD}{m["id"]}\n')
    return "\n".join(lines)


# =============================
# MAIN
# =============================

if __name__ == "__main__":
    print("📺 Fetching FIFA+ livestreams (via proxy fallback)...")

    if not BASE_URLS:
        print("❌ BASE_URLS kosong! Pastikan file chinzyaigodata_file.txt berisi variabel BASE_URLS.")
        exit(1)

    all_matches = fetch_matches()
    all_matches.sort(key=lambda x: x["title"])

    m3u_output = build_m3u(all_matches)
    filename = "CHINZYAGIO.m3u"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(m3u_output)

    print(f"✅ Saved to {filename} ({len(all_matches)} matches)")
