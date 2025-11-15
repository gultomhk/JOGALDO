import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

# =======================
# 🔧 KONFIGURASI
# =======================
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

# ====== MASUKKAN cf_clearance DI SINI ======
CF_CLEARANCE = "E_T2StX3Nu0cQ4BVe0d74L5Ml5yNI4GZc78G_JsxdYM-1763177652-1.2.1.1-X.f1lWa1iwxtkxOL6MhQSz4bzALdKL2cI.GsMMgF3zgIOTFweNBi._CRVkYnolVm1buBm1oyHj.vKQ_tGg0BIQNCSPO7ftzHMO9yPtzKrGr_8aSb3uVlvVV_xZgsGsqwLB.UQCdFFbl2INWWT6Q454vkL4ZrVYhRm9asJxQWfxyfNPOVF2HCYZOC4.G1pmgYPajUtX3ViW8.MBs0_TH313eqvHQ6BF7TNwQDroQowqY"

# =======================
# 🔧 EXTRA HEADERS (full browser fingerprint)
# =======================
EXTRA_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": USER_AGENT,
}

# =======================
# 🔧 UTILITAS
# =======================
async def scroll_page(page):
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height

# =======================
# 🔧 SCRAPER DENGAN COOKIE CF_CLEARANCE + EXTRA HEADERS
# =======================
async def fetch_dynamic_html_playwright():
    async with async_playwright() as p:
        print(f"🌐 Membuka halaman: {DEFAULT_URL}")

        try:
            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 768}
            )

            # Inject cookie cf_clearance
            await context.add_cookies([
                {
                    "name": "cf_clearance",
                    "value": CF_CLEARANCE,
                    "domain": ".fstv.space",
                    "path": "/"
                }
            ])

            # Inject EXTRA_HEADERS ke setiap request
            await context.route("**/*", 
                lambda route, request: route.continue_(headers={
                    **request.headers,
                    **EXTRA_HEADERS
                })
            )

            page = await context.new_page()

            # Load halaman
            await page.goto(DEFAULT_URL, timeout=60000)
            await page.wait_for_load_state("networkidle")

            print("📜 Scrolling halaman...")
            await scroll_page(page)

            try:
                await page.wait_for_selector(".slide-item, .common-table-row", timeout=30000)
            except:
                print("⚠️ Selector utama tidak ditemukan, lanjut simpan HTML.")

            # Klik tab Server (jika ada)
            try:
                tab_button = await page.query_selector("button:has-text('Server')")
                if tab_button:
                    print("🖱️ Klik tab 'Server'...")
                    await tab_button.click()
                    await page.wait_for_timeout(2000)
            except:
                print("⚠️ Tidak ada tab 'Server' ditemukan.")

            # Simpan HTML
            html = await page.content()
            with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
                f.write(html)

            print("✅ HTML berhasil disimpan ke BODATTV_PAGE_SOURCE.html")
            await browser.close()

        except Exception as e:
            print(f"❌ Gagal memuat halaman: {e}")
            with open("BODATTV_PAGE_SOURCE.html", "w", encoding="utf-8") as f:
                f.write("")

# =======================
# 🚀 JALANKAN
# =======================
if __name__ == "__main__":
    asyncio.run(fetch_dynamic_html_playwright())
