import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re
import json
from pathlib import Path
import sys

CONFIG_FILE = Path.home() / "926data_file.txt"
OUTPUT_FILE = "map4.json"

# --- Load config ---
def load_config(filepath):
    config = {}
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    config[key.strip()] = val.strip().strip('"')
    except FileNotFoundError:
        print(f"❌ Config file not found at {filepath}")
        sys.exit(1)
    return config

config = load_config(CONFIG_FILE)
BASE_URL = config.get("BASE_URL")
if not BASE_URL:
    print("❌ BASE_URL not found in config")
    sys.exit(1)

# --- Ambil daftar live IDs ---
async def get_live_ids(page):
    await page.goto(BASE_URL)
    await page.wait_for_timeout(3000)
    soup = BeautifulSoup(await page.content(), "html.parser")
    live_ids = [a["href"].split("/")[-1] for a in soup.find_all("a", href=True) if a["href"].startswith("/bofang/")]
    print(f"Found {len(live_ids)} live IDs:", live_ids)
    return live_ids

# --- Ambil m3u8 untuk 1 ID ---
async def fetch_m3u8(context, lid):
    page = await context.new_page()
    m3u8_url = None

    async def on_request(request):
        nonlocal m3u8_url
        if ".m3u8" in request.url:
            m3u8_url = request.url

    page.on("request", on_request)

    try:
        url = f"{BASE_URL}/live/{lid}"
        print(f"🎯 Live URL: {url}")
        
        await page.goto(url, wait_until="commit", timeout=15000)

        # Tunggu network traffic muncul (max 10 detik)
        for _ in range(20):
            if m3u8_url:
                break
            await asyncio.sleep(0.5)

        if m3u8_url:
            print(f"   ✅ Found .m3u8: {m3u8_url}")
            return lid, m3u8_url.strip()
        else:
            print(f"   ❌ Tidak ditemukan .m3u8 untuk {lid}")
            return lid, None

    except Exception as e:
        print(f"   ❌ Error {lid}: {e}")
        return lid, None
    finally:
        await page.close()

# --- Main ---
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=config.get("USER_AGENT") or None)

        # Ambil daftar ID
        page = await context.new_page()
        live_ids = await get_live_ids(page)
        await page.close()

        # Ambil semua m3u8 paralel
        tasks = [fetch_m3u8(context, lid) for lid in live_ids]
        results_data = await asyncio.gather(*tasks)

        # Simpan hasil
        results = {lid: link for lid, link in results_data if link}
        print("\n📦 Ringkasan hasil:")
        for lid, link in results.items():
            print(f"{lid}: {link}")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Disimpan ke {OUTPUT_FILE}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
