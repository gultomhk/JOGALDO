from pathlib import Path
from playwright.sync_api import sync_playwright
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import time

# ==========================
# Load Config dari chinlagi1data_file.txt
# ==========================
CHINLAGI1DATA_FILE = Path.home() / "chinlagi1data_file.txt"

config_vars = {}
with open(CHINLAGI1DATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

UA = config_vars.get("UA")
REFERER = config_vars.get("REFERER")
BASE_URL = config_vars.get("BASE_URL")
WORKER_TEMPLATE = config_vars.get("WORKER_TEMPLATE")
DEFAULT_LOGO = config_vars.get("DEFAULT_LOGO")

OUT_FILE = "chinlagi1_matches.m3u"

# Jakarta tz
try:
    from zoneinfo import ZoneInfo
    JAKARTA = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = timezone(timedelta(hours=7))


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
                    if kickoff_ts > 1_000_000_000_000:  # ms -> s
                        kickoff_ts //= 1000
                except Exception:
                    kickoff_ts = None
            time_str = ""
            if kickoff_ts:
                try:
                    dt = datetime.fromtimestamp(kickoff_ts, tz=timezone.utc).astimezone(JAKARTA)
                    time_str = dt.strftime("%d/%m-%H.%M")
                except Exception:
                    time_str = ""
            title = f"{time_str} {home or ''} vs {away or ''} ({tname})".strip()
            out.append({
                "iid": str(iid) if iid is not None else None,
                "home": home or "",
                "away": away or "",
                "kickoff": kickoff_ts,
                "title": title,
                "logo": (m.get("logo") or "") or DEFAULT_LOGO,
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


def fetch_with_retry(page, url: str, max_retries: int = 3) -> Dict[str, Any]:
    """Fetch dengan retry mechanism"""
    for attempt in range(max_retries):
        try:
            # Gunakan approach yang lebih reliable
            js_code = """
            async () => {
                try {
                    const response = await fetch('%s', {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json, text/javascript, */*',
                            'User-Agent': '%s',
                            'Referer': '%s'
                        },
                        mode: 'cors'
                    });
                    
                    if (!response.ok) {
                        return {error: `HTTP ${response.status}: ${response.statusText}`};
                    }
                    
                    const data = await response.json();
                    return {success: true, data: data};
                } catch (error) {
                    return {error: error.toString()};
                }
            }
            """ % (url, UA, REFERER)
            
            result = page.evaluate(js_code)
            
            if result.get('success'):
                return result['data']
            else:
                print(f"[ATTEMPT {attempt + 1}] Fetch failed: {result.get('error')}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Tunggu 2 detik sebelum retry
                    
        except Exception as e:
            print(f"[ATTEMPT {attempt + 1}] Exception: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    return {}


def main():
    all_matches = []
    
    print(f"[INFO] Using User-Agent: {UA[:50]}...")
    print(f"[INFO] Using Referer: {REFERER}")
    
    with sync_playwright() as p:
        # Tambahkan options untuk better compatibility
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--allow-running-insecure-content',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "referer": REFERER,
                "accept": "application/json, text/javascript, */*",
                "accept-language": "id-ID,id;q=0.9,en;q=0.8",
            }
        )
        
        # Set extra headers untuk page
        page = context.new_page()
        
        # Navigate ke referer dulu untuk set cookies
        try:
            print("[INFO] Setting up browser context...")
            page.goto(REFERER, wait_until="networkidle", timeout=30000)
            time.sleep(3)
        except Exception as e:
            print(f"[WARN] Could not navigate to referer: {e}")

        urls_to_fetch = []
        for sid in range(1, 5):
            for params in (
                {"sid": sid, "sort": "tournament", "inplay": "true", "language": "id-id"},
                {"sid": sid, "sort": "tournament", "inplay": "false", "date": "24h", "language": "id-id"},
            ):
                qs = "&".join(f"{k}={params[k]}" for k in params)
                url = f"{BASE_URL}?{qs}"
                urls_to_fetch.append(url)

        total_urls = len(urls_to_fetch)
        for i, url in enumerate(urls_to_fetch, 1):
            print(f"[{i}/{total_urls}] Fetching: {url.split('?')[0]}...")
            
            result = fetch_with_retry(page, url)
            
            if result:
                matches = extract_matches(result)
                all_matches.extend(matches)
                print(f"[OK] Found {len(matches)} matches")
            else:
                print(f"[ERROR] Failed to fetch data from {url}")
            
            # Delay antar request
            if i < total_urls:
                time.sleep(1)

        browser.close()

    if not all_matches:
        print("[ERROR] No matches fetched at all!")
        return

    # dedupe by iid
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

    # filter: buang yang kickoff sudah lewat lebih dari 2 jam
    now = datetime.now(JAKARTA)
    filtered = []
    for m in uniq.values():
        kickoff_ts = m.get("kickoff")
        if kickoff_ts:
            event_time = datetime.fromtimestamp(kickoff_ts, tz=JAKARTA)
            if event_time < (now - timedelta(hours=2)):
                continue
        filtered.append(m)

    final = sorted(filtered, key=lambda x: (x.get("kickoff") is None, x.get("kickoff") or 0))

    if not final:
        print("[WARN] No matches found after filtering.")
    else:
        write_m3u(final)
        print(f"[SUCCESS] Total {len(final)} matches processed")


if __name__ == "__main__":
    main()
