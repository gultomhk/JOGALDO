from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
import urllib.parse
from playwright.sync_api import sync_playwright
import time

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {CONFIG_FILE}")

config = load_config(CONFIG_FILE)
BASE_URL = config["BASE_URL"]
USER_AGENT = config["USER_AGENT"]
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": BASE_URL
}

now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========= Parser player?link= → nilai link (ENCODED) + extra params =========
def parse_player_link(url: str, keep_encoded: bool = True) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    if "link" not in qs:
        return url  # bukan format player

    # ambil nilai 'link' persis (encoded string)
    encoded_link_value = qs["link"][0]

    # gabungkan semua param tambahan selain 'link'
    extras = {k: v for k, v in qs.items() if k != "link"}
    extra_str = urlencode(extras, doseq=True) if extras else ""

    if keep_encoded:
        # hasilnya tetap encoded seperti contohmu
        return encoded_link_value + (("&" + extra_str) if extra_str else "")
    else:
        # decode jadi URL https://... lalu tempel param ekstra
        decoded = unquote(encoded_link_value)
        if extra_str:
            if "?" in decoded:
                decoded += "&" + extra_str
            else:
                decoded += "?" + extra_str
        return decoded

# ========= Pembersih hasil URL =========
def clean_m3u8_links(urls, keep_encoded=True):
    cleaned = []
    for u in set(urls):
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)  # pakai parser kita
            # encoded string masih mengandung ".m3u8" sebagai teks, jadi tetap lolos filter
        if ".m3u8" in u:
            cleaned.append(u)
    return cleaned

# ========= Fungsi Ekstraksi M3U8 dengan Playwright =========
def extract_m3u8_with_playwright(slug):
    """Ekstrak URL m3u8 menggunakan Playwright untuk menangani JavaScript"""
    print(f"   🚀 Menggunakan Playwright untuk: {slug}")
    
    with sync_playwright() as p:
        # Gunakan browser headless
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        
        try:
            # Navigasi ke halaman
            page.goto(f"{BASE_URL}/match/{slug}", timeout=30000)
            
            # Tunggu hingga elemen player dimuat
            page.wait_for_timeout(5000)  # Tunggu 5 detik untuk memastikan JavaScript selesai dieksekusi
            
            # Coba cari iframe player
            iframe_element = page.query_selector("iframe[src*='link=']")
            
            if iframe_element:
                # Dapatkan src dari iframe
                iframe_src = iframe_element.get_attribute("src")
                if iframe_src:
                    # Parse URL iframe untuk mendapatkan parameter link
                    parsed_url = urlparse(urljoin(BASE_URL, iframe_src))
                    query_params = parse_qs(parsed_url.query)
                    m3u8_encoded = query_params.get("link", [""])[0]
                    
                    if m3u8_encoded:
                        m3u8_url = unquote(m3u8_encoded)
                        if ".m3u8" in m3u8_url:
                            print(f"   ✅ M3U8 ditemukan via Playwright: {m3u8_url}")
                            return [m3u8_url]
            
            # Alternatif: Cari elemen dengan data-link
            data_link_elements = page.query_selector_all("[data-link]")
            m3u8_urls = []
            
            for element in data_link_elements:
                data_link = element.get_attribute("data-link")
                if data_link and data_link.endswith(".m3u8") and data_link.startswith("http"):
                    print(f"   ✅ M3U8 ditemukan via Playwright (data-link): {data_link}")
                    m3u8_urls.append(data_link)
            
            if m3u8_urls:
                return m3u8_urls
            
            # Alternatif lain: Coba tangkap request network yang mengandung m3u8
            print(f"   ⚠️ Mencoba intercept network requests untuk: {slug}")
            
            # List untuk menampung URL m3u8 yang ditemukan
            captured_urls = []
            
            def handle_request(request):
                url = request.url
                if ".m3u8" in url and "geotarget" not in url.lower():
                    captured_urls.append(url)
                    print(f"   🔍 Terdeteksi request m3u8: {url}")
            
            # Pasang listener untuk request
            page.on("request", handle_request)
            
            # Refresh halaman untuk menangkap request
            page.reload(timeout=30000)
            page.wait_for_timeout(8000)  # Tunggu lebih lama untuk menangkap request
            
            # Hapus listener setelah selesai
            page.remove_listener("request", handle_request)
            
            if captured_urls:
                # Hapus duplikat
                unique_urls = list(set(captured_urls))
                print(f"   ✅ M3U8 ditemukan via network interception: {unique_urls[0]}")
                return unique_urls
            
            return []
            
        except Exception as e:
            print(f"   ❌ Error dengan Playwright untuk {slug}: {e}")
            return []
        finally:
            browser.close()

# ========= Fungsi Ekstraksi M3U8 =========
def extract_m3u8_urls(html):
    """Ekstrak URL m3u8 dari HTML dengan berbagai metode"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if raw.endswith(".m3u8") and raw.startswith("http"):
            print(f"   🔗 Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)
        elif "/player?link=" in raw:
            decoded = urllib.parse.unquote(raw)
            if decoded.endswith(".m3u8") and decoded.startswith("http"):
                print(f"   🔗 Dari iframe: ✅ {decoded}")
                m3u8_urls.append(decoded)
            else:
                print(f"   ⚠️ Iframe tapi bukan m3u8: {raw}")
        else:
            print(f"   ⚠️ Skip: {raw}")
    
    # Bersihkan URL menggunakan fungsi clean_m3u8_links
    m3u8_urls = clean_m3u8_links(m3u8_urls, keep_encoded=False)
    return m3u8_urls

# ========= Ambil daftar slug =========
def extract_slug(row):
    """Ekstrak slug dari elemen baris HTML."""
    # Coba dari atribut onclick dulu
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    
    # Fallback ke <a href="/match/...">
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    
    return None


def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")

    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            # ⏰ Ambil timestamp pertandingan
            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
                waktu = event_time_local.strftime("%d/%m-%H.%M")
            else:
                waktu = "00/00-00.00"
                event_time_local = now

            # 🔴 Cek apakah sedang live
            is_live = row.select_one(".live-text") is not None

            # ⏩ Skip jika lewat waktu threshold & bukan live
            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

            # 🚫 Skip keyword pengecualian
            slug_lower = slug.lower()
            is_exception = any(
                keyword in slug_lower
                for keyword in ["tennis", "billiards", "snooker", "worldssp", "superbike"]
            )
            if not is_live and not is_exception and event_time_local < (now - timedelta(hours=hours_threshold)):
                continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Simpan ke MAP =========
def save_to_map(slugs):
    new_data = {}

    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{len(slugs)}] ▶ Scraping slug: {slug}", flush=True)

        try:
            # Pertama coba dengan requests biasa
            r = requests.get(f"{BASE_URL}/match/{slug}", headers=HEADERS, timeout=15)
            r.raise_for_status()

            # Ekstrak m3u8 dari halaman HTML
            m3u8_urls = extract_m3u8_urls(r.text)

            # Fallback ke iframe player jika belum ketemu
            if not m3u8_urls:
                soup = BeautifulSoup(r.text, "html.parser")
                iframe = soup.select_one("iframe[src*='link=']")
                if iframe:
                    m3u8_encoded = parse_qs(
                        urlparse(urljoin(BASE_URL, iframe["src"])).query
                    ).get("link", [""])[0]
                    m3u8_url = unquote(m3u8_encoded)
                    if ".m3u8" in m3u8_url:
                        m3u8_urls.append(m3u8_url)

            # Jika masih belum ketemu, gunakan Playwright
            if not m3u8_urls:
                m3u8_urls = extract_m3u8_with_playwright(slug)

            # Bersihkan URL sebelum disimpan
            m3u8_urls = clean_m3u8_links(m3u8_urls, keep_encoded=False)

            # Simpan hasil
            if m3u8_urls:
                if len(m3u8_urls) == 1:
                    # hanya 1 server → slug polos
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 ditemukan: {m3u8_urls[0]}", flush=True)
                else:
                    # server1 → slug polos
                    new_data[slug] = m3u8_urls[0]
                    print(f"   ✅ M3U8 ditemukan (server1): {m3u8_urls[0]}", flush=True)

                    # server2,3,... → slugserver2, slugserver3, dst.
                    for i, url in enumerate(m3u8_urls[1:], start=2):
                        key = f"{slug}server{i}"
                        new_data[key] = url
                        print(f"   ✅ M3U8 ditemukan (server{i}): {url}", flush=True)
            else:
                print(f"   ⚠️ Tidak ditemukan .m3u8 pada slug: {slug}", flush=True)

        except Exception as e:
            print(f"   ❌ Error saat proses slug '{slug}': {e}", flush=True)

    # Simpan hanya data baru yang berhasil
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)

    print(f"✅ map2.json berhasil disimpan! Total entri berhasil: {len(new_data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    save_to_map(slug_list)
