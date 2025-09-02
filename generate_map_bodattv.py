import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
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
now = datetime.now(tz.gettz("Asia/Jakarta"))

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

# ========= Extract slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    return None

# ========= Extract slugs dari HTML =========
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
    seen = set()
    for u in urls:
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)
        if (
            ".m3u8" in u
            and "404" not in u
            and "google.com" not in u
            and "adexchangeclear" not in u
            and u not in seen
        ):
            cleaned.append(u)
            seen.add(u)
    return cleaned

# ========= Server-2..N pakai Selenium =========
def fetch_server_2n_selenium(slug, driver_path="chromedriver"):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={USER_AGENT}")

    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    m3u8_links = []
    try:
        main_url = f"{BASE_URL}/match/{slug}"
        driver.get(main_url)
        time.sleep(5)

        buttons = driver.find_elements(By.CSS_SELECTOR, ".btn-server[data-link]")
        for idx, btn in enumerate(buttons, start=2):
            try:
                btn.click()
                time.sleep(2)
                elems = driver.find_elements(
                    By.CSS_SELECTOR,
                    "#player-html5 iframe[src*='player?link='], #player-html5 source[src$='.m3u8']"
                )
                for elem in elems:
                    link = elem.get_attribute("src")
                    if link and link not in m3u8_links:
                        link = urljoin(BASE_URL, link)
                        print(f"✅ Server-{idx}: {link}")
                        m3u8_links.append(link)
            except Exception as e:
                print(f"⚠️ Gagal ambil Server-{idx}: {e}")

    finally:
        driver.quit()
    return m3u8_links

# ========= Playwright fetch m3u8 per slug (Server-1) =========
async def fetch_m3u8_server1_playwright(context, slug, keep_encoded=True):
    page_links = []
    page = await context.new_page()

    def handle_response(response):
        resp_url = response.url
        if ".m3u8" in resp_url and resp_url not in page_links:
            print(f"✅ Server-1: m3u8 terdeteksi {resp_url}")
            page_links.append(resp_url)

    page.on("response", handle_response)
    try:
        main_url = f"{BASE_URL}/match/{slug}"
        await page.goto(main_url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        iframe = await page.query_selector(".iframe-wrapper iframe[src*='player?link=']")
        if iframe:
            iframe_src = await iframe.get_attribute("src")
            iframe_src = urljoin(BASE_URL, iframe_src)
            print(f"✅ Server-1: iframe default {iframe_src}")
            page_links.append(iframe_src)
        else:
            print("⚠️ Server-1 iframe tidak ditemukan")
    except Exception as e:
        print(f"❌ Error Server-1: {e}")
    finally:
        await page.close()

    return clean_m3u8_links(page_links, keep_encoded=keep_encoded)

# ========= Fetch semua slug hybrid =========
async def fetch_m3u8_hybrid(context, slug, keep_encoded=True):
    links_server1 = await fetch_m3u8_server1_playwright(context, slug, keep_encoded)
    links_server2n = fetch_server_2n_selenium(slug)
    all_links = links_server1 + links_server2n

    # Hapus duplikat tapi jaga urutan
    seen, unique_links = set(), []
    for l in all_links:
        if l not in seen:
            unique_links.append(l)
            seen.add(l)
    return slug, unique_links

# ========= Jalankan semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_hybrid(context, slug, keep_encoded=keep_encoded)

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
                    key = f"{slug}server{i}"
                    all_data[key] = url
        return all_data

# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

# ========= MAIN =========
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=5, keep_encoded=True))
    save_map_file(all_data)
