import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright

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
def clean_m3u8_links(urls, keep_encoded=True):
    cleaned = []
    for u in set(urls):
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)
        if ".m3u8" in u:
            cleaned.append(u)
    return cleaned

# ========= Playwright fetch m3u8 per server =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    page = await context.new_page()
    m3u8_links = []
    server_links = {}  # Dictionary untuk menyimpan link per server

    def handle_request(request):
        url = request.url
        # Tangkap hanya request m3u8 yang mengandung auth_key
        if ".m3u8" in url and "auth_key" in url:
            # Identifikasi server berdasarkan domain atau pattern
            server_name = "server1"  # Default
            if "o2." in url:
                server_name = "server2"
            elif "o3." in url:
                server_name = "server3"
            elif "o4." in url:
                server_name = "server4"
            
            # Simpan dengan key server yang berbeda
            if server_name not in server_links:
                server_links[server_name] = []
            server_links[server_name].append(url)
            print(f"   🔍 Terdeteksi {server_name}: {url}")

    page.on("request", handle_request)

    try:
        await page.goto(f"{BASE_URL}/match/{slug}", timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)  # Tunggu lebih lama untuk menangkap semua request

        # Klik semua tombol server yang tersedia
        server_buttons = await page.query_selector_all("button, div[onclick*='server'], .server-btn, .stream-option")
        
        for i, button in enumerate(server_buttons):
            try:
                # Klik tombol server
                await button.click()
                await page.wait_for_timeout(3000)  # Tunggu request setelah klik
                print(f"   🖱️ Diklik server button {i+1}")
            except Exception as e:
                print(f"   ⚠️ Gagal klik server button {i+1}: {e}")

        # Jika tidak ada server buttons, coba cari iframe
        if not server_links:
            iframes = await page.query_selector_all("iframe[src*='player?link=']")
            for iframe in iframes:
                src = await iframe.get_attribute("src")
                if src:
                    full_url = urljoin(BASE_URL, src)
                    parsed_url = parse_player_link(full_url, keep_encoded=keep_encoded)
                    if ".m3u8" in parsed_url:
                        # Identifikasi server
                        server_name = "server1"
                        if "o2." in parsed_url:
                            server_name = "server2"
                        elif "o3." in parsed_url:
                            server_name = "server3"
                        elif "o4." in parsed_url:
                            server_name = "server4"
                        
                        if server_name not in server_links:
                            server_links[server_name] = []
                        server_links[server_name].append(parsed_url)
                        print(f"   🔍 Iframe {server_name}: {parsed_url}")

    except Exception as e:
        print(f"   ❌ Error buka {slug}: {e}")
    finally:
        await page.close()

    # Kumpulkan semua link unik per server
    final_links = []
    for server_name, links in server_links.items():
        if links:
            # Ambil link pertama untuk setiap server (biasanya yang terbaik)
            final_links.append(links[0])
    
    return slug, clean_m3u8_links(final_links, keep_encoded=keep_encoded)

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
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

            slug, urls = slug_result
            if urls:
                if len(urls) == 1:
                    # hanya 1 server → slug polos
                    all_data[slug] = urls[0]
                    print(f"   ✅ M3U8 ditemukan: {urls[0]}", flush=True)
                else:
                    # server1 → slug polos
                    all_data[slug] = urls[0]
                    print(f"   ✅ M3U8 ditemukan (server1): {urls[0]}", flush=True)

                    # server2,3,... → slugserver2, slugserver3, dst.
                    for i, url in enumerate(urls[1:], start=2):
                        key = f"{slug}server{i}"
                        all_data[key] = url
                        print(f"   ✅ M3U8 ditemukan (server{i}): {url}", flush=True)
            else:
                print(f"   ⚠️ Tidak ditemukan .m3u8 pada slug: {slug}", flush=True)

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

    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8, keep_encoded=True))
    save_map_file(all_data)
