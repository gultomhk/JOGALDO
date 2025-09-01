import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urljoin
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

# ========= Ambil slug =========
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
                continue

            seen.add(slug)
            slugs.append(slug)
        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Fetch server dengan authkey via Playwright =========
async def fetch_m3u8_servers(context, slug):
    servers = []
    main_url = f"{BASE_URL}/match/{slug}"
    page = await context.new_page()
    try:
        await page.goto(main_url, timeout=30000, wait_until="networkidle")
        await page.wait_for_timeout(4000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # gabungkan tombol server + iframe
        items = []

        # tombol server
        server_buttons = soup.select(".list-server button[data-link]")
        for btn in server_buttons:
            btn_url = btn.get("data-link")
            if btn_url:
                items.append(urljoin(BASE_URL, btn_url))

        # iframe player?link=
        iframes = soup.select("iframe[src*='player?link=']")
        for iframe in iframes:
            iframe_src = urljoin(BASE_URL, iframe["src"])
            items.append(iframe_src)

        # proses semua item
        for idx, url in enumerate(items, start=1):
            page_links = []

            def handle_response(response):
                resp_url = response.url
                if ".m3u8" in resp_url and resp_url not in page_links:
                    page_links.append(resp_url)

            temp_page = await context.new_page()
            temp_page.on("response", handle_response)
            try:
                await temp_page.goto(url, timeout=30000, wait_until="networkidle")
                await temp_page.wait_for_timeout(7000)  # kasih waktu player load
            except Exception as e:
                print(f"   ❌ Error load {url}: {e}")
            await temp_page.close()

            if page_links:
                servers.append(page_links[0])
                print(f"   ✅ M3U8 server{idx}: {page_links[0]}")
            else:
                print(f"   ⚠️ Gagal ambil server{idx} dari {url}")

    except Exception as e:
        print(f"   ❌ Error fetch slug {slug}: {e}")
    finally:
        await page.close()

    # hapus duplikat sambil jaga urutan
    seen = set()
    unique_servers = []
    for s in servers:
        if s not in seen:
            unique_servers.append(s)
            seen.add(s)

    return slug, unique_servers

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, extra_http_headers={"Referer": BASE_URL})
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_servers(context, slug)

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
                for i, url in enumerate(urls[1:], start=2):
                    all_data[f"{slug}server{i}"] = url
            else:
                print(f"⚠️ Tidak ditemukan .m3u8 pada slug: {slug}")

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

    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8))
    save_map_file(all_data)
