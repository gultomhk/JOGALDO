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
USER_AGENT = config.get("USER_AGENT", "Mozilla/5.0")


async def scroll_page(page):
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height


async def fetch_dynamic_html_playwright(retries=3):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        for attempt in range(1, retries + 1):
            try:
                print(f"🌐 Visiting FSTV (attempt {attempt}/{retries}): {DEFAULT_URL}")
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
                return  # sukses, keluar dari fungsi

            except Exception as e:
                print(f"❌ Error on attempt {attempt}: {e}")
                await page.screenshot(path=f"error_attempt{attempt}.png", full_page=True)
                if attempt < retries:
                    print("🔄 Retrying in 10s...")
                    await asyncio.sleep(10)
                else:
                    print("⛔ All retries failed, saving empty file...")
                    with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
                        f.write("")
                    await browser.close()
                    return


if __name__ == "__main__":
    asyncio.run(fetch_dynamic_html_playwright())
