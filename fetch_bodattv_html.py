import os
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

# Baca config dari file
FSTVDATA_FILE = Path.home() / "fstvdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

config = load_config(FSTVDATA_FILE)
DEFAULT_URL = config.get("DEFAULT_URL")

async def fetch_fstv_html():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=config.get("USER_AGENT"))
        page = await context.new_page()

        print(f"🌐 Visiting FSTV: {DEFAULT_URL}")
        await page.goto(DEFAULT_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        await page.wait_for_selector('.slide-item, .common-table-row', timeout=60000)
        await page.mouse.wheel(0, 8000)
        await page.wait_for_timeout(3000)

        html = await page.content()
        with open("FSTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ Saved full page source to FSTV_PAGE_SOURCE.html")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(fetch_fstv_html())
