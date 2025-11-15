import requests
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError

# ==========================
# KONFIGURASI
# ==========================
cvvpdata_FILE = Path.home() / "cvvpdata_file.txt"
config_vars = {}

with open(cvvpdata_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

PPV_API_URL = config_vars.get("PPV_API_URL")
OUTPUT_FILE = Path("map8.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

# ============================================================
# Ambil semua iframe dari PPV API
# ============================================================
def get_all_iframes():
    print("📺 Mengambil event dari PPV.to...")

    r = requests.get(PPV_API_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()

    results = []
    data = r.json()

    for cat in data.get("streams", []):
        for stream in cat.get("streams", []):
            iframe = stream.get("iframe")
            if iframe:
                results.append(iframe)

    print(f"✅ Total iframe ditemukan: {len(results)}")
    return results


# ============================================================
# Resolver SINGLE (gunakan browser yang sama)
# ============================================================
async def resolve_single(browser, url):
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"
    )
    page = await context.new_page()

    await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    """)

    found = None

    def on_request(req):
        nonlocal found
        if ".m3u8" in req.url:
            found = req.url

    page.on("request", on_request)

    try:
        await page.goto(url, timeout=0)
    except:
        pass

    for _ in range(60):
        if found:
            break
        await asyncio.sleep(0.5)

    await context.close()
    return found


# ============================================================
# Resolver MULTI paralel
# ============================================================
SEM = asyncio.Semaphore(6)  # batasi 6 iframe sekaligus (aman untuk GitHub Actions)

async def worker(browser, url, results, index, total):
    async with SEM:
        print(f"\n[{index}/{total}] ▶ {url}")
        try:
            m3u8 = await resolve_single(browser, url)
            print("🔥 M3U8:", m3u8)
            results[url] = m3u8
        except Exception as e:
            print("❌ ERROR:", e)
            results[url] = None


async def resolve_all(iframes):
    results = {}
    print("🚀 Resolving semua iframe SECARA PARALEL...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=[
                "--disable-gpu-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-infobars",
                "--ignore-certificate-errors",
                "--use-gl=swiftshader",
                "--no-sandbox",
                "--window-size=1280,720",
            ]
        )

        tasks = []
        total = len(iframes)

        for idx, iframe in enumerate(iframes, start=1):
            tasks.append(worker(browser, iframe, results, idx, total))

        await asyncio.gather(*tasks)

        await browser.close()

    print("🎯 Semua selesai.")
    return results


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    iframes = get_all_iframes()

    data = asyncio.run(resolve_all(iframes))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 map8.json berhasil dibuat → {OUTPUT_FILE.absolute()}")
