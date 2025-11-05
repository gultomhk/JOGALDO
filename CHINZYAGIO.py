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

FIFA_BASE_URLS = config_vars.get("FIFA_BASE_URLS")
PROXY_LIST_URL = config_vars.get("PROXY_LIST_URL")
DOMAIN_DRM = config_vars.get("DOMAIN_DRM")
DOMAIN_MPD = config_vars.get("DOMAIN_MPD")
EVENT_TVG_LOGO = config_vars.get("EVENT_TVG_LOGO")

FIFA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
    "Accept": "application/json, text/plain, */*"
}

FIFA_TIMEZONE_OFFSET = timedelta(hours=7)  # WIB


# ===================================
# AMBIL DAFTAR PROXY
# ===================================
def load_proxies():
    try:
        print("🌐 Mengunduh daftar proxy...")
        res = requests.get(PROXY_LIST_URL, timeout=10)
        res.raise_for_status()
        proxies = [p.strip() for p in res.text.splitlines() if p.strip()]
        print(f"✅ {len(proxies)} proxy ditemukan.")
        return proxies
    except Exception as e:
        print(f"⚠️ Gagal memuat proxy: {e}")
        return []


# ===================================
# KONFIGURASI DAN UJI PROXY
# ===================================
def proxy_config(proxy_str):
    if proxy_str.startswith("socks5://") or ":1080" in proxy_str:
        scheme = "socks5"
    elif proxy_str.startswith("socks4://"):
        scheme = "socks4"
    else:
        scheme = "http"
    proxy_clean = proxy_str.replace("socks5://", "").replace("socks4://", "")
    return {"http": f"{scheme}://{proxy_clean}", "https": f"{scheme}://{proxy_clean}"}


def find_working_proxy(test_url, headers, proxy_list):
    """Cari satu proxy yang sukses"""
    random.shuffle(proxy_list)
    for proxy in proxy_list:
        try:
            conf = proxy_config(proxy)
            print(f"🔌 Mencoba proxy: {conf['http']}")
            res = requests.get(test_url, headers=headers, proxies=conf, timeout=10)
            if res.status_code == 200:
                print("✅ Proxy sukses:", proxy)
                return conf
        except Exception:
            print(f"❌ Proxy gagal: {proxy}")
    print("⚠️ Tidak ada proxy yang berhasil, lanjut tanpa proxy.")
    return None


# ===================================
# FETCH DATA DARI FIFA+
# ===================================
def get_fifa_matches():
    print("📺 Mengambil event dari FIFA+...")
    proxies = load_proxies()
    global_proxy = None

    # Cari proxy pertama yang berhasil
    if proxies:
        global_proxy = find_working_proxy(FIFA_BASE_URLS[0], FIFA_HEADERS, proxies)

    matches = []
    for url in FIFA_BASE_URLS:
        print(f"🔗 Fetching from: {url}")
        try:
            if global_proxy:
                res = requests.get(url, headers=FIFA_HEADERS, proxies=global_proxy, timeout=15)
            else:
                res = requests.get(url, headers=FIFA_HEADERS, timeout=15)

            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"⚠️ Gagal mengambil dari {url}: {e}")
            continue

        results = data.get("results") or data.get("items") or []
        print(f"📊 Found {len(results)} items")

        for item in results:
            if "id" not in item:
                continue

            id_ = item["id"]
            title = item.get("title") or item.get("standardTitle") or "Untitled"
            logo = (
                item.get("wideCoverUrl")
                or item.get("backdropUri")
                or item.get("posterImage", {}).get("url", "")
                or EVENT_TVG_LOGO
            )

            start = item.get("startDate")
            if not start:
                continue

            try:
                dt_utc = datetime.fromisoformat(start.replace("Z", "+00:00"))
                dt_wib = dt_utc + FIFA_TIMEZONE_OFFSET
                date_str = dt_wib.strftime("%d/%m-%H.%M")
            except Exception:
                date_str = "??/??-??.??"

            if "|" in title:
                parts = title.split("|", 1)
                match_name = parts[0].strip().replace(" v ", " vs ")
                tournament = parts[1].strip()
                formatted_title = f"{match_name} ({tournament})"
            else:
                formatted_title = title.strip().replace(" v ", " vs ")

            entry = {
                "id": id_,
                "title": f"{date_str} {formatted_title}",
                "logo": logo,
            }
            matches.append(entry)

    # =========================
    # OUTPUT M3U
    # =========================
    outputs = ["#EXTM3U"]
    for m in matches:
        outputs.append(f'#EXTINF:-1 tvg-logo="{m["logo"]}" group-title="⚽️| LIVE EVENT",{m["title"]}')
        outputs.append("#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0")
        outputs.append("#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha")
        outputs.append(f'#KODIPROP:inputstream.adaptive.license_key={DOMAIN_DRM}{m["id"]}')
        outputs.append(f'{DOMAIN_MPD}{m["id"]}\n')

    print(f"✅ FIFA+ matches found: {len(matches)}")
    return "\n".join(outputs)


# ===================================
# MAIN
# ===================================
if __name__ == "__main__":
    output_text = get_fifa_matches()

    # Simpan hasil ke file
    filename = "CHINZYAGIO.m3u"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"\n💾 Output disimpan ke: {filename}")
