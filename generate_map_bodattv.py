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

# ========= Filter URL yang valid =========
def is_valid_m3u8_url(url):
    """Filter URL yang benar-benar valid m3u8"""
    # Tolak URL yang mengandung domain tidak diinginkan
    invalid_domains = ["google.com", "fstv.online/404", "adexchangeclear.com", "google.com/sorry"]
    if any(domain in url for domain in invalid_domains):
        return False
    
    # Hanya terima URL dari domain yang diinginkan
    valid_domains = ["sundaytueday.online", "skysport", "espn"]
    if not any(domain in url for domain in valid_domains):
        return False
    
    # Pastikan ini adalah URL m3u8
    if ".m3u8" not in url:
        return False
        
    return True

# ========= Parser player?link= → nilai link (ENCODED) + extra params =========
def parse_player_link(url: str, keep_encoded: bool = True) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "link" not in qs:
        return url
    encoded_link_value = qs["link"][0]
    extras = {k: v for k, v in qs.items() if k != "link"}
    extra_str = urlencode(extras, doseq=True) if extras else ""
    if keep_encoded:
        return encoded_link_value + (("&" + extra_str) if extra_str else "")
    else:
        decoded = unquote(encoded_link_value)
        if extra_str:
            decoded += "&" + extra_str if "?" in decoded else "?" + extra_str
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

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            is_live = row.select_one(".live-text") is not None

            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

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
        if is_valid_m3u8_url(u):
            cleaned.append(u)
    return cleaned

# ========= Deteksi server berbeda berdasarkan path =========
def group_links_by_server(links):
    """Kelompokkan link berdasarkan path (bukan query parameters)"""
    servers = {}
    for link in links:
        parsed = urlparse(link)
        # Gunakan netloc + path sebagai kunci server
        server_key = f"{parsed.netloc}{parsed.path}"
        if server_key not in servers:
            servers[server_key] = []
        servers[server_key].append(link)
    
    # Ambil hanya 1 URL per server (yang pertama)
    unique_servers = {}
    for server_key, server_links in servers.items():
        unique_servers[server_key] = server_links[0]
    
    return list(unique_servers.values())

# ========= Playwright fetch m3u8 per slug =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    m3u8_links = []

    async def process_page(url):
        page_links = []
        page = await context.new_page()

        def handle_request(request):
            req_url = request.url
            if is_valid_m3u8_url(req_url) or "player?link=" in req_url:
                page_links.append(req_url)

        page.on("request", handle_request)

        try:
            await page.goto(url, timeout=40000, wait_until="networkidle")
            # Tunggu lebih lama untuk memastikan semua konten terload
            await page.wait_for_timeout(8000)
            
            # Coba klik tombol server jika ada
            server_buttons = await page.query_selector_all("button, div[onclick*='server'], a[href*='server']")
            for button in server_buttons:
                try:
                    await button.click()
                    await page.wait_for_timeout(2000)
                except:
                    pass
                    
        except Exception as e:
            print(f"   ❌ Error buka page {url}: {e}")
        finally:
            await page.close()

        return clean_m3u8_links(page_links, keep_encoded=keep_encoded)

    # buka slug utama
    main_url = f"{BASE_URL}/match/{slug}"
    print(f"   🔍 Membuka: {main_url}")
    main_links = await process_page(main_url)
    m3u8_links.extend(main_links)

    # fallback: semua iframe player?link= di halaman utama
    try:
        page = await context.new_page()
        await page.goto(main_url, timeout=40000, wait_until="networkidle")
        await page.wait_for_timeout(5000)
        
        # Cari semua elemen yang mungkin mengandung link alternatif
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Cari iframe
        iframes = soup.select("iframe[src*='player?link=']")
        for iframe in iframes:
            iframe_src = urljoin(BASE_URL, iframe["src"])
            print(f"   🔍 Membuka iframe: {iframe_src}")
            iframe_links = await process_page(iframe_src)
            m3u8_links.extend(iframe_links)
            
        # Cari elemen dengan data-link atau atribut serupa
        data_links = soup.select("[data-link], [data-src], [data-url]")
        for elem in data_links:
            for attr in ['data-link', 'data-src', 'data-url']:
                if elem.has_attr(attr):
                    link_value = elem[attr]
                    if "m3u8" in link_value or "player?link=" in link_value:
                        full_link = urljoin(BASE_URL, link_value)
                        m3u8_links.append(full_link)
                        
    except Exception as e:
        print(f"   ❌ Error iframe slug {slug}: {e}")
    finally:
        await page.close()

    # Bersihkan dan kelompokkan link
    m3u8_links = clean_m3u8_links(m3u8_links, keep_encoded=keep_encoded)
    m3u8_links = group_links_by_server(m3u8_links)
    
    return slug, m3u8_links

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080}
        )
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
                all_data[slug] = urls[0]
                print(f"   ✅ M3U8 ditemukan (server1): {urls[0]}", flush=True)
                # Ambil semua server yang unik
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
