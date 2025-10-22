import asyncio
import random
import re
import aiohttp
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
USER_AGENT = config.get("USER_AGENT")
PROXYLIST_URL = config.get("UPROXYLIST_URL")


# 🔹 Ambil daftar proxy US dari GitHub
async def fetch_proxy_list():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PROXYLIST_URL, timeout=15) as resp:
                text = await resp.text()
                proxies = re.findall(r"(\d+\.\d+\.\d+\.\d+:\d+)", text)
                return proxies
    except Exception as e:
        print(f"⚠️ Gagal mengambil proxy list: {e}")
        return []


async def scroll_page(page):
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height


async def fetch_dynamic_html_playwright(retries=5):
    proxies = await fetch_proxy_list()
    print(f"🌎 Loaded {len(proxies)} US proxies from GitHub list")

    if not proxies:
        print("❌ Tidak ada proxy yang bisa digunakan.")
        return

    async with async_playwright() as p:
        for attempt in range(1, retries + 1):
            proxy = random.choice(proxies)
            print(f"🌐 Attempt {attempt}/{retries} using proxy: {proxy}")

            # Proxy Playwright harus diterapkan di `launch()`
            launch_args = {
                "headless": True,
                "proxy": {"server": f"http://{proxy}"}
            }

            try:
                browser = await p.firefox.launch(**launch_args)
                context = await browser.new_context(user_agent=USER_AGENT)
                page = await context.new_page()

                await page.goto(DEFAULT_URL, timeout=60000)
                await page.wait_for_load_state("networkidle")

                # 🔍 --- Deteksi Cloudflare Challenge ---
                content = await page.content()
                if any(
                    s in content for s in [
                        "cf-challenge", "cf-error-details",
                        "captcha", "Checking your browser before accessing"
                    ]
                ):
                    print("⚠️ Cloudflare challenge detected! Changing proxy...\n")
                    raise Exception("Cloudflare challenge detected")
                # --- Akhir deteksi ---

                print("📜 Scrolling page...")
                await scroll_page(page)
                await page.wait_for_selector(".slide-item, .common-table-row", timeout=30000)

                # Optional klik tab
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

                print(f"✅ Success with proxy {proxy}")
                await browser.close()
                return

            except Exception as e:
                print(f"❌ Error on attempt {attempt}: {e}")
                if 'browser' in locals():
                    await browser.close()
                await asyncio.sleep(5)

                if attempt < retries:
                    print("🔄 Retrying with new proxy...\n")
                else:
                    print("⛔ All retries failed, saving empty file...")
                    with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
                        f.write("")
                    return


if __name__ == "__main__":
    asyncio.run(fetch_dynamic_html_playwright())
