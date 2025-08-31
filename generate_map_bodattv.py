import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright
from collections import defaultdict

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
now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========= Parser player?link= → nilai link (ENCODED) + extra params =========
def parse_player_link(url: str, keep_encoded: bool = False) -> str:
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

# ========= Ambil daftar slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
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
            else:
                event_time_local = now

            # 🔴 Cek apakah sedang live
            is_live = row.select_one(".live-text") is not None

            # ⏩ Skip jika lewat waktu threshold & bukan live
            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

            # 🚫 Optional pengecualian kategori
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

# ========= Pembersih hasil URL =========
def clean_m3u8_links(urls, keep_encoded=False):
    cleaned = []
    for u in set(urls):
        original_u = u
        # Jika URL mengandung player?link=, parse untuk extract m3u8 dengan auth_key
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)
            print(f"   🔄 Parsed player link: {original_u} -> {u}")
        
        # Pastikan URL mengandung .m3u8
        if ".m3u8" in u:
            cleaned.append(u)
    return cleaned

# ========= Playwright fetch m3u8 per server =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=False):
    page = await context.new_page()
    server_links = {}  # Dictionary untuk menyimpan link per server
    server_counter = 1  # Counter untuk server yang ditemukan
    domain_to_server = {}  # Mapping domain ke nomor server

    def handle_request(request):
        nonlocal server_counter
        url = request.url
        
        # Tangkap request yang mengandung player?link= atau m3u8 langsung
        if "player?link=" in url or (".m3u8" in url and "auth_key" in url):
            # Parse URL untuk mendapatkan URL m3u8 lengkap dengan auth_key
            if "player?link=" in url:
                parsed_url = parse_player_link(url, keep_encoded=keep_encoded)
            else:
                parsed_url = url
            
            if ".m3u8" in parsed_url:
                # Ekstrak domain dari URL
                try:
                    domain = urlparse(parsed_url).netloc
                except:
                    domain = "unknown"
                
                # Jika domain sudah pernah dilihat, gunakan nomor server yang sama
                if domain in domain_to_server:
                    server_name = f"server{domain_to_server[domain]}"
                else:
                    # Domain baru, beri nomor server baru
                    server_name = f"server{server_counter}"
                    domain_to_server[domain] = server_counter
                    server_counter += 1
                
                server_links[server_name] = parsed_url
                print(f"   🔍 Terdeteksi {server_name} ({domain}): {parsed_url}")

    page.on("request", handle_request)

    try:
        await page.goto(f"{BASE_URL}/match/{slug}", timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)  # Tunggu lebih lama untuk menangkap semua request

        # Coba klik semua elemen yang mungkin menjadi tombol server/quality
        selectors_to_try = [
            "button",
            "div[onclick*='server']",
            "div[onclick*='quality']",
            "div[onclick*='stream']",
            ".server-btn",
            ".quality-btn",
            ".stream-btn",
            ".stream-option",
            ".quality-option",
            "[class*='server']",
            "[class*='quality']",
            "[class*='stream']"
        ]
        
        for selector in selectors_to_try:
            try:
                buttons = await page.query_selector_all(selector)
                for i, button in enumerate(buttons):
                    try:
                        # Klik tombol server/quality
                        await button.click()
                        await page.wait_for_timeout(2000)  # Tunggu request setelah klik
                        print(f"   🖱️ Diklik {selector} #{i+1}")
                    except Exception as e:
                        # Skip error klik, lanjut ke tombol berikutnya
                        continue
            except Exception as e:
                # Skip error selector, lanjut ke selector berikutnya
                continue

    except Exception as e:
        print(f"   ❌ Error buka {slug}: {e}")
    finally:
        await page.close()

    return slug, server_links

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_with_playwright(context, slug, keep_encoded=keep_encoded)

        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        await browser.close()

        all_data = {}
        for slug_result in results:
            if isinstance(slug_result, Exception):
                print(f"❌ Error di task: {slug_result}")
                continue

            slug, server_urls = slug_result
            if server_urls:
                # Simpan semua server yang ditemukan
                server_count = len(server_urls)
                print(f"   ✅ Ditemukan {server_count} server untuk {slug}")
                
                # Urutkan server berdasarkan nomor (server1, server2, server3, dst.)
                sorted_servers = sorted(server_urls.items(), key=lambda x: int(x[0].replace('server', '')))
                
                for i, (server_name, url) in enumerate(sorted_servers, 1):
                    if i == 1:
                        # Server pertama → slug polos
                        all_data[slug] = url
                        print(f"   ✅ M3U8 ditemukan ({server_name}): {url}")
                    else:
                        # Server lainnya → slugserver2, slugserver3, dst.
                        key = f"{slug}{server_name}"
                        all_data[key] = url
                        print(f"   ✅ M3U8 ditemukan ({server_name}): {url}")
            else:
                print(f"   ⚠️ Tidak ditemukan .m3u8 pada slug: {slug}")

        return all_data
        
# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)

    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8, keep_encoded=False))
    save_map_file(all_data)
