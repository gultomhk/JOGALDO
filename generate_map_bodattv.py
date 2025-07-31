import asyncio
import json
import re
from urllib.parse import unquote
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime, timedelta, timezone
from dateutil import tz

# ===== Config & Constants =====
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

# ===== Slug Extraction =====
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
    now = datetime.now(tz.gettz("Asia/Jakarta"))
    slugs = []
    seen = set()
    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue
            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(tz.gettz("Asia/Jakarta"))
                if event_time < now - timedelta(hours=hours_threshold):
                    continue
            seen.add(slug)
            slugs.append(slug)
        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ===== M3U8 Extraction per Slug =====
async def get_m3u8_links_from_slug(slug):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        m3u8_links = []

        try:
            print(f"🔗 Visiting: {BASE_URL}/match/{slug}")
            await page.goto(f"{BASE_URL}/match/{slug}", timeout=60000)
            await page.wait_for_selector("iframe", timeout=15000)
            buttons = await page.query_selector_all("button:has-text('Server')")

            for i, button in enumerate(buttons):
                try:
                    await button.click()
                    await page.wait_for_timeout(2500)
                    iframe_el = await page.query_selector("iframe")
                    iframe_src = await iframe_el.get_attribute("src")
                    if not iframe_src:
                        continue
                    new_page = await context.new_page()
                    await new_page.goto(iframe_src, timeout=20000)
                    await new_page.wait_for_load_state("networkidle")
                    content = await new_page.content()
                    await new_page.close()

                    found = re.findall(r'https?://[^\s\'"]+\.m3u8', content)
                    for url in found:
                        if url not in m3u8_links:
                            m3u8_links.append(unquote(url))
                            print(f"   ✅ Found: {url}")
                except Exception as e:
                    print(f"   ⚠️ Gagal load server {i+1}: {e}")
        except Exception as e:
            print(f"❌ Error slug {slug}: {e}")
        finally:
            await browser.close()
        return m3u8_links

# ===== Save Map =====
async def save_to_map(slugs):
    old_data = {}
    if MAP_FILE.exists():
        with MAP_FILE.open(encoding="utf-8") as f:
            old_data = json.load(f)

    new_data = {}
    for idx, slug in enumerate(slugs, 1):
        print(f"[{idx}/{len(slugs)}] ▶ Processing slug: {slug}")
        links = await get_m3u8_links_from_slug(slug)
        if links:
            new_data[slug] = links

    combined = {**old_data, **new_data}
    ordered = {k: combined[k] for k in slugs if k in combined}
    limited = dict(list(ordered.items())[-100:])

    if not MAP_FILE.exists() or json.dumps(limited, sort_keys=True) != json.dumps(old_data, sort_keys=True):
        with MAP_FILE.open("w", encoding="utf-8") as f:
            json.dump(limited, f, indent=2, ensure_ascii=False)
        print(f"✅ map2.json berhasil disimpan. Total: {len(limited)} entri")
    else:
        print("ℹ️ Tidak ada perubahan. map2.json tidak diubah.")

# ===== Main =====
async def main():
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")
    html = html_path.read_text(encoding="utf-8")
    slugs = extract_slugs_from_html(html)
    await save_to_map(slugs)

# Jalankan
if __name__ == "__main__":
    asyncio.run(main())
