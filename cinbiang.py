import asyncio
import json
import html
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Request

# =======================
CONFIG_FILE = Path.home() / "steramest2data_file.txt"
OUTPUT_FILE = "map4.json"
LIMIT_MATCHES = 5  # 🔹 ambil 5 pertandingan terdekat
# =======================

# --- load config dari file ---
config = {}
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            config[key.strip()] = val.strip().strip('"').strip("'")

# wajib ada BASE_URL dan USER_AGENT
if "BASE_URL" not in config or "USER_AGENT" not in config:
    raise ValueError("⚠️ steramest2data_file.txt harus berisi BASE_URL dan USER_AGENT")

BASE_URL = config["BASE_URL"]
UA = config["USER_AGENT"]
INDEX_URL = f"{BASE_URL}/index/"

# --- helper ambil daftar pertandingan ---
def fetch_matches():
    headers = {"User-Agent": UA}
    res = requests.get(INDEX_URL, headers=headers, timeout=20)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    matches = []
    for li in soup.select("li.f1-podium--item"):
        a = li.find("a")
        if not a:
            continue
        slug = a.get("href", "")
        time_el = li.select_one(".SaatZamanBilgisi")
        if not time_el:
            continue

        ts = time_el.get("data-zaman")
        if ts and ts.isdigit():
            dt = datetime.fromtimestamp(int(ts))
        else:
            try:
                dt = datetime.strptime(time_el.get_text(strip=True), "%d.%m.%Y %I:%M %p")
            except:
                dt = None

        matches.append({"slug": slug, "datetime": dt})
    return matches

# --- helper safe_goto ---
async def safe_goto(page, url, tries=2, timeout=20000):
    for attempt in range(tries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            html_content = await page.content()
            if any(x in html_content.lower() for x in ["cloudflare", "just a moment", "attention required"]):
                await asyncio.sleep(2)
                continue
            return True
        except Exception as e:
            print(f"⚠️ Error loading {url}: {e}")
            await asyncio.sleep(2)
    return False

# --- scrape m3u8 ---
async def scrape_stream_url(context, url):
    m3u8_links = set()
    page = await context.new_page()

    def capture_request(request: Request):
        if ".m3u8" in request.url.lower() and not m3u8_links:
            print(f"🎯 Found stream: {request.url}")
            m3u8_links.add(request.url)

    page.on("request", capture_request)

    try:
        if not await safe_goto(page, url):
            return []
        await asyncio.sleep(1)
        await page.mouse.click(500, 500)
        for _ in range(20):
            if m3u8_links:
                break
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"⚠️ Error scraping {url}: {e}")
    finally:
        await page.close()

    # bersihkan HTML entities di URL
    return [html.unescape(u) for u in m3u8_links]

# --- main ---
async def main():
    matches = fetch_matches()
    print(f"📊 Total matches ditemukan: {len(matches)}")

    matches = [m for m in matches if m["datetime"]]
    matches.sort(key=lambda m: m["datetime"])
    matches = matches[:LIMIT_MATCHES]

    print(f"🗓️ Akan di-scrape {len(matches)} pertandingan terdekat:")
    for m in matches:
        print(f" - {m['slug']} ({m['datetime']})")

    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        for m in matches:
            slug = m["slug"].lstrip("/")
            url = f"{BASE_URL}/{slug}"
            print(f"\n🔍 Scraping {url}")
            links = await scrape_stream_url(context, url)
            if links:
                results[m["slug"]] = links[0]
            else:
                print(f"❌ Tidak ada stream ketemu di {slug}")

        await browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Saved results to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
