import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright

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
        except:
            continue
    return slugs

def filter_valid_m3u8(urls):
    return [u for u in urls if ".m3u8" in u and "404" not in u and "google.com" not in u and "adexchangeclear" not in u]

async def fetch_m3u8_from_page(context, url, keep_encoded=True):
    page_links = set()
    page = await context.new_page()
    page.on("response", lambda resp: page_links.add(resp.url) if ".m3u8" in resp.url else None)
    try:
        await page.goto(url, timeout=30000, wait_until="networkidle")
        await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"❌ Error page {url}: {e}")
    finally:
        await page.close()
    final_links = []
    for u in page_links:
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded)
        final_links.append(u)
    final_links = filter_valid_m3u8(final_links)
    return final_links  # ambil semua URL unik

async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    urls = []
    main_url = f"{BASE_URL}/match/{slug}"
    first_links = await fetch_m3u8_from_page(context, main_url, keep_encoded)
    urls.extend(first_links)

    # iframe player?link=
    page = await context.new_page()
    try:
        await page.goto(main_url, timeout=30000, wait_until="networkidle")
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        iframes = soup.select("iframe[src*='player?link=']")
        for iframe in iframes:
            iframe_src = urljoin(BASE_URL, iframe["src"])
            iframe_links = await fetch_m3u8_from_page(context, iframe_src, keep_encoded)
            for link in iframe_links:
                if link not in urls:
                    urls.append(link)
    except Exception as e:
        print(f"❌ Error iframe slug {slug}: {e}")
    finally:
        await page.close()

    # susun server1, server2, server3
    data = {}
    for i, u in enumerate(urls, start=1):
        key = slug if i == 1 else f"{slug}server{i}"
        data[key] = u
    return data

async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
    all_data = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        semaphore = asyncio.Semaphore(concurrency)
        async def sem_task(slug):
            async with semaphore:
                return await fetch_m3u8_with_playwright(context, slug, keep_encoded)
        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            all_data.update(r)
        await browser.close()
    return all_data

def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")
    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)
    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8, keep_encoded=True))
    save_map_file(all_data)
