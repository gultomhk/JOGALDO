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

    # basic stealth-ish
    await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    """)

    # Hook early to capture player-injected m3u8 BEFORE player runs
    await page.add_init_script("""
    window.__CAPTURED_M3U8 = null;
    (function(){
      try{
        // Clappr hook (safe)
        Object.defineProperty(window, 'Clappr', {
          configurable: true,
          set: function(v){
            try{
              if(v && v.Player){
                var OldPlayer = v.Player;
                v.Player = function(cfg){
                  try{ if(cfg && cfg.source && cfg.source.indexOf('.m3u8')!=-1) window.__CAPTURED_M3U8 = cfg.source; }catch(e){}
                  return new OldPlayer(cfg);
                };
              }
            }catch(e){}
            Object.defineProperty(window, 'Clappr', { value: v, configurable: true, writable: true });
          },
          get: function(){
            return undefined;
          }
        });
      }catch(e){}
      try{
        // JWPlayer proxy (safe)
        var _orig_jw = window.jwplayer;
        window.jwplayer = function(){
          var p = (_orig_jw && _orig_jw.apply(this, arguments)) || {};
          try{
            if(p && p.setup){
              var oldSetup = p.setup;
              p.setup = function(cfg){
                try{
                  var f = null;
                  if(cfg){
                    if(cfg.file) f = cfg.file;
                    else if(cfg.sources && cfg.sources.length) f = (cfg.sources[0].file || cfg.sources[0].file);
                  }
                  if(f && f.indexOf && f.indexOf('.m3u8') !== -1) window.__CAPTURED_M3U8 = f;
                }catch(e){}
                return oldSetup.call(this, cfg);
              }
            }
          }catch(e){}
          return p;
        };
      }catch(e){}
    })();
    """)

    found = None

    def on_request(req):
        nonlocal found
        try:
            if ".m3u8" in req.url:
                found = req.url
        except:
            pass

    page.on("request", on_request)

    try:
        await page.goto(url, timeout=0)
    except Exception:
        # ignore navigation errors, continue to try to extract
        pass

    # 1) Quick scan: regex in the current HTML (some players inline the m3u8 after render)
    try:
        html = await page.content()
        import re
        m = re.search(r'https?://[^"\'\\s]+\.m3u8', html)
        if m:
            candidate = m.group(0)
            await context.close()
            return candidate
    except Exception:
        pass

    # 2) Check the injected JS-captured variable (from add_init_script)
    try:
        for _ in range(20):
            captured = await page.evaluate("window.__CAPTURED_M3U8")
            if captured:
                await context.close()
                return captured
            # maybe player needs a bit to initialize
            await asyncio.sleep(0.25)
    except Exception:
        pass

    # 3) Try to click common play buttons (some players only request streams after play)
    play_selectors = [
        "button.play", "button.jwplay", ".jwplay", "button.vjs-big-play-button",
        "button.play-btn", ".play-btn", "div.play-btn", "button[aria-label='Play']",
        ".plyr__control--play", ".clappr-play", ".playpause"
    ]
    for sel in play_selectors:
        try:
            btns = await page.query_selector_all(sel)
            if btns:
                for b in btns:
                    try:
                        await b.click(timeout=2000)
                        # small wait to allow network requests
                        await asyncio.sleep(0.5)
                        if found:
                            await context.close()
                            return found
                    except Exception:
                        continue
        except Exception:
            continue

    # 4) Wider wait loop: watch for network requests or captured var
    try:
        for _ in range(120):  # up to ~30s
            if found:
                await context.close()
                return found
            try:
                captured = await page.evaluate("window.__CAPTURED_M3U8")
                if captured:
                    await context.close()
                    return captured
            except Exception:
                pass
            await asyncio.sleep(0.25)
    except Exception:
        pass

    # 5) fallback: try searching iframe content (some players put config inside nested iframe DOM)
    try:
        frames = page.frames
        import re
        for f in frames:
            try:
                f_html = await f.content()
                m = re.search(r'https?://[^"\'\\s]+\.m3u8', f_html)
                if m:
                    await context.close()
                    return m.group(0)
            except Exception:
                continue
    except Exception:
        pass

    await context.close()
    return None


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
