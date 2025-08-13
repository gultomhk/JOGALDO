import os
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import requests

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
BASE_URL = config.get("BASE_URL1")  # ambil BASE_URL1 sebagai BASE_URL

# Fungsi 1: download dengan requests
def download_static_html():
    OUTPUT_FILE = "926page_source.html"

    headers = {
        "User-Agent": config.get("USER_AGENT", "Mozilla/5.0")
    }

    print(f"🔄 Downloading HTML from {BASE_URL} ...")
    response = requests.get(BASE_URL, headers=headers)
    response.raise_for_status()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(response.text)

    print(f"✅ HTML saved to {OUTPUT_FILE}")

# Fungsi 2: fetch pakai Playwright
async def scroll_page(page):
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height

async def fetch_dynamic_html_playwright():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=config.get("USER_AGENT"))
        page = await context.new_page()

        print(f"🌐 Visiting FSTV: {DEFAULT_URL}")
        await page.goto(DEFAULT_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        print("📜 Scrolling page...")
        await scroll_page(page)

        await page.wait_for_selector('.slide-item, .common-table-row', timeout=30000)

        try:
            tab_button = await page.query_selector("button:has-text('Server')")
            if tab_button:
                print("🖱️ Clicking server tab...")
                await tab_button.click()
                await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"⚠️ No server tab found or error: {e}")

        html = await page.content()
        with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ Saved full page source to BODATTV_PAGE_SOURCE.html")

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['static', 'dynamic'], default='dynamic',
                        help="Pilih mode: 'static' untuk requests, 'dynamic' untuk playwright")
    args = parser.parse_args()

    if args.mode == 'static':
        download_static_html()
    else:
        asyncio.run(fetch_dynamic_html_playwright())
