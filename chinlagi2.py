import asyncio
import json
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright
import httpx
from pathlib import Path

# ==========================
# Load Config
# ==========================
CHINLAGI2DATA_FILE = Path.home() / "chinlagi2data_file.txt"

config_vars = {}
with open(CHINLAGI2DATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

UA = config_vars.get("UA")
REFERER = config_vars.get("REFERER")
WORKER_TEMPLATE = config_vars.get("WORKER_TEMPLATE")
DEFAULT_LOGO = config_vars.get("DEFAULT_LOGO")
BASE_URL = config_vars.get("BASE_URL")
PROXY_LIST_URL = config_vars.get("PROXY_LIST_URL")

URLS = [
    f"{BASE_URL}?sid=1&sort=tournament&inplay=true&language=id-id",
    f"{BASE_URL}?sid=1&sort=tournament&inplay=false&date=24h&language=id-id",
]

try:
    from zoneinfo import ZoneInfo
    JAKARTA = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = timezone(timedelta(hours=7))

OUT_FILE = "CHIN2_matches.m3u"

def extract_matches(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    data = payload.get("data") or {}
    tournaments = data.get("tournaments") or []
    for t in tournaments:
        tname = t.get("name") or t.get("tnName") or ""
        for m in t.get("matches", []):
            iid = m.get("iid") or m.get("id")
            home = (m.get("home") or {}).get("name") if isinstance(m.get("home"), dict) else m.get("home")
            away = (m.get("away") or {}).get("name") if isinstance(m.get("away"), dict) else m.get("away")
            kickoff = m.get("kickoffTime")
            kickoff_ts = None
            if kickoff is not None:
                try:
                    kickoff_ts = int(kickoff)
                    if kickoff_ts > 1_000_000_000_000:
                        kickoff_ts //= 1000
                except:
                    pass
            time_str = ""
            if kickoff_ts:
                try:
                    dt = datetime.fromtimestamp(kickoff_ts, tz=timezone.utc).astimezone(JAKARTA)
                    time_str = dt.strftime("%d/%m-%H.%M")
                except:
                    pass
            title = f"{time_str} {home or ''} vs {away or ''} ({tname})".strip()
            out.append({
                "iid": str(iid) if iid else None,
                "home": home or "",
                "away": away or "",
                "kickoff": kickoff_ts,
                "title": title,
                "logo": (m.get("logo") or "") or DEFAULT_LOGO,
            })
    # fallback minimal
    if not out:
        out.append({
            "iid": None,
            "home": "NoMatch",
            "away": "NoMatch",
            "kickoff": None,
            "title": "No Match Available",
            "logo": DEFAULT_LOGO
        })
    return out

def write_m3u(matches: List[Dict[str, Any]], path: str = OUT_FILE):
    lines = ["#EXTM3U"]
    for m in matches:
        title = m.get("title") or f"{m.get('home')} vs {m.get('away')}"
        logo = m.get("logo") or DEFAULT_LOGO
        lines.append(f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{logo}",{title}')
        lines.append(f"#EXTVLCOPT:http-user-agent={UA}")
        lines.append(f"#EXTVLCOPT:http-referrer={REFERER}")
        iid = m.get("iid")
        if iid:
            lines.append(WORKER_TEMPLATE.format(iid=iid))
        else:
            lines.append("# no-iid-found")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Saved {len(matches)} entries to {path}")

async def fetch_proxy_list() -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(PROXY_LIST_URL)
            proxies = [line.strip() for line in r.text.splitlines() if line.strip() and not line.startswith("#")]
            return proxies
    except:
        return []

async def try_fetch_page(page, url):
    js = f"""
    fetch("{url}", {{
        method: "GET",
        headers: {{
            "Referer": "{REFERER}",
            "User-Agent": "{UA}"
        }}
    }}).then(r => r.text()).catch(e => "__fetch_fail__")
    """
    return await page.evaluate(js)

async def main():
    proxies = await fetch_proxy_list()
    if not proxies:
        proxies = [None]  # fallback no proxy
    results = []

    async with async_playwright() as p:
        for proxy in proxies:
            print(f"[INFO] mencoba proxy: {proxy or 'default'}")
            try:
                browser = await p.chromium.launch(headless=True, proxy={"server": proxy} if proxy else None)
                context = await browser.new_context(user_agent=UA)
                page = await context.new_page()

                try:
                    await page.goto(REFERER, timeout=15000)
                    print("[INFO] Referer page loaded")
                except:
                    print("[WARN] gagal buka referer page")

                for url in URLS:
                    raw = await try_fetch_page(page, url)
                    if raw == "__fetch_fail__":
                        print(f"[ERROR] {url} via {proxy} fetch gagal")
                        continue
                    try:
                        data = json.loads(raw)
                        results.append({"url": url, "data": data, "proxy": proxy})
                        print(f"[OK] {url} via {proxy}")
                    except Exception as e:
                        print(f"[ERROR] {url} via {proxy}: {e}")

                await browser.close()
                if results:
                    break
            except Exception as e:
                print(f"[WARN] Proxy {proxy} gagal: {e}")

    # simpan hasil JSON (selalu ada output)
    output_json_path = "result_raw.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(results or [{"msg": "No data fetched"}], f, ensure_ascii=False, indent=2)
    print(f"[DONE] {output_json_path} tersimpan, {len(results)} item")

    # --- generate M3U dari hasil ---
    all_matches = []
    for item in results:
        data = item.get("data") or {}
        if isinstance(data, dict):
            matches = extract_matches(data)
            all_matches.extend(matches)

    # filter unik berdasarkan iid
    uniq = {}
    for m in all_matches:
        iid = m.get("iid")
        if not iid:
            continue
        if iid in uniq:
            ex = uniq[iid]
            if (m.get("kickoff") or 10**18) < (ex.get("kickoff") or 10**18):
                uniq[iid] = m
        else:
            uniq[iid] = m

    final_matches = list(uniq.values())
    if final_matches:
        write_m3u(final_matches)
    else:
        print("[WARN] Tidak ada match valid untuk M3U, menulis dummy entry")
        write_m3u([{
            "iid": None,
            "home": "NoMatch",
            "away": "NoMatch",
            "kickoff": None,
            "title": "No Match Available",
            "logo": DEFAULT_LOGO
        }])

asyncio.run(main())
