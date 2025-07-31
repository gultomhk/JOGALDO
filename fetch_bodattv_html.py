import os
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BODATTVDATA_FILE = Path.home() / "bodattvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

config = load_config(BODATTVDATA_FILE)
DEFAULT_URL = config.get("DEFAULT_URL")

async def scroll_page(page):
    # Scroll pelan-pelan sampai mentok
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height

async def fetch_fstv_html():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=config.get("USER_AGENT"))
        page = await context.new_page()

        print(f"🌐 Visiting FSTV: {DEFAULT_URL}")
        await page.goto(DEFAULT_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        # Scroll ke bawah sampai mentok
        print("📜 Scrolling page...")
        await scroll_page(page)

        # Tunggu elemen utama dan tombol/tab server muncul
        await page.wait_for_selector('.slide-item, .common-table-row', timeout=30000)

        # Coba klik tab jika ada
        try:
            tab_button = await page.query_selector("button:has-text('Server')")  # ganti sesuai teks tab jika perlu
            if tab_button:
                print("🖱️ Clicking server tab...")
                await tab_button.click()
                await page.wait_for_timeout(2000)
        except:
            print("⚠️ No server tab found.")

        html = await page.content()
        with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ Saved full page source to BODATTV_PAGE_SOURCE.html")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(fetch_fstv_html())
