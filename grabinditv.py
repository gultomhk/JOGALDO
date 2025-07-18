from playwright.sync_api import sync_playwright
import re, json
from pathlib import Path

# Load config dari indidata_file.txt
INDIDATA_FILE = Path.home() / "indidata_file.txt"
config = {}
exec(INDIDATA_FILE.read_text(encoding="utf-8"), config)

headers = config["headers"]
channel_ids = config["channel_ids"]
url_template = config["url_template"]

def get_mpd_url(channel_id, page):
    try:
        url = url_template.format(channel_id=channel_id)
        page.goto(url, timeout=10000)
        html = page.content()
        mpd = re.search(r"var\s+v\d+\s*=\s*'(https://[^']+\.mpd[^']*)'", html)
        if not mpd:
            Path(f"debug_{channel_id}.html").write_text(html, encoding="utf-8")
        return mpd.group(1) if mpd else None
    except Exception as e:
        print(f"❌ Error {channel_id}: {e}")
        return None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent=headers["User-Agent"])
    page = context.new_page()

    result_map = {}
    for cid in channel_ids:
        mpd_url = get_mpd_url(cid, page)
        if mpd_url:
            result_map[cid] = mpd_url
            print(f"✅ {cid}: {mpd_url}")
        else:
            print(f"⚠️  {cid}: MPD not found")

    Path("map3.json").write_text(json.dumps(result_map, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n📁 map3.json berhasil dibuat.")
    browser.close()
