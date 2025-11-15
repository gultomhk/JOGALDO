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
# 🔧 UTILITAS
# =======================
async def scroll_page(page):
    """Scroll halaman hingga tidak bertambah tinggi lagi."""
    previous_height = None
    while True:
        current_height = await page.evaluate("document.body.scrollHeight")
        if previous_height == current_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        previous_height = current_height

# =======================
# 🔧 SCRAPER DENGAN COOKIE CF_CLEARANCE
# =======================
async def fetch_dynamic_html_playwright():
    async with async_playwright() as p:
        print(f"🌐 Membuka halaman: {DEFAULT_URL}")

        try:
            # Chromium wajib untuk Cloudflare
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 768}
            )

            # Inject cookie Cloudflare clearance
            await context.add_cookies([
                {
                    "name": "cf_clearance",
                    "value": CF_CLEARANCE,
                    "domain": ".fstv.space",
                    "path": "/"
                }
            ])

            page = await context.new_page()

            # Akses langsung, Cloudflare tidak akan muncul
            await page.goto(DEFAULT_URL, timeout=60000)
            await page.wait_for_load_state("networkidle")

            print("📜 Scrolling halaman...")
            await scroll_page(page)

            # Tunggu konten muncul
            try:
                await page.wait_for_selector(".slide-item, .common-table-row", timeout=30000)
            except:
                print("⚠️ Selector utama tidak ditemukan, lanjut simpan HTML.")

            # Klik tab Server bila ada
            try:
                tab_button = await page.query_selector("button:has-text('Server')")
                if tab_button:
                    print("🖱️ Klik tab 'Server'...")
                    await tab_button.click()
                    await page.wait_for_timeout(2000)
            except Exception:
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
