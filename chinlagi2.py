import asyncio
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from pathlib import Path
from playwright.async_api import async_playwright
import sys

# ==========================
# Auto flush log supaya realtime di console/CI
# ==========================
print = lambda *args, **kwargs: (__builtins__.print(*args, **kwargs), sys.stdout.flush())

# ==========================
# Load Config dari chinlagi2data_file.txt
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
PROXY_URL = config_vars.get("PROXY_URL")

OUT_FILE = "CHIN2_matches.m3u"

try:
    from zoneinfo import ZoneInfo
    JAKARTA = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = timezone(timedelta(hours=7))

# ==========================
# Load proxy list
# ==========================
proxy_list = []
if PROXY_URL:
    try:
        with urllib.request.urlopen(PROXY_URL) as resp:
            proxy_list = [x.strip() for x in resp.read().decode().splitlines() if x.strip()]
        print(f"[INFO] Loaded {len(proxy_list)} proxies from {PROXY_URL}")
    except Exception as e:
        print(f"[WARN] gagal ambil proxy list: {e}")

working_proxy = None  # <--- inisialisasi global


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


async def try_fetch(p, url, proxy):
    """Launch browser dengan proxy tertentu"""
    try:
        print(f"[DEBUG] Launching browser with proxy={proxy}")
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy} if proxy else None
        )
        context = await browser.new_context(
            user_agent=UA,
            extra_http_headers={"referer": REFERER}
        )
        page = await context.new_page()
        js = f"""
            async () => {{
                const ctrl = new AbortController();
                const id = setTimeout(() => ctrl.abort(), 10000);
                try {{
                    const r = await fetch("{url}", {{
                        method: "GET",
                        headers: {{
                            "User-Agent": "{UA}",
                            "Referer": "{REFERER}"
                        }},
                        signal: ctrl.signal
                    }});
                    clearTimeout(id);
                    const text = await r.text();
                    try {{
                        return JSON.parse(text);
                    }} catch(e) {{
                        return {{__error:"parse-fail", raw:text}};
                    }}
                }} catch(err) {{
                    return null;
                }}
            }}
        """
        result = await page.evaluate(js)
        await browser.close()
        if result and result.get("data"):
            print(f"[OK] Fetch sukses dengan proxy={proxy}")
        else:
            print(f"[FAIL] Tidak ada data dengan proxy={proxy}")
        return result if result and result.get("data") else None
    except Exception as e:
        print(f"[ERR] proxy {proxy} gagal: {e}")
        return None


async def fetch_with_proxy(p, url: str):
    global working_proxy

    if working_proxy:
        print(f"[TRY] pakai proxy {working_proxy}")
        result = await try_fetch(p, url, working_proxy)
        if result:
            return result
        else:
            print(f"[WARN] Proxy {working_proxy} gagal, reset.")
            working_proxy = None

    for proxy in proxy_list:
        print(f"[TRY] proxy {proxy}")
        result = await try_fetch(p, url, proxy)
        if result:
            working_proxy = proxy
            print(f"[OK] Gunakan proxy {proxy} untuk seterusnya")
            return result
    return None


async def main():
    all_matches = []
    async with async_playwright() as p:
        for sid in range(1, 5):
            for params in (
                {"sid": sid, "sort": "tournament", "inplay": "true", "language": "id-id"},
                {"sid": sid, "sort": "tournament", "inplay": "false", "date": "24h", "language": "id-id"},
            ):
                qs = "&".join(f"{k}={params[k]}" for k in params)
                url = f"{BASE_URL}?{qs}"
                print(f"\n[FETCH] {url}")
                result = await fetch_with_proxy(p, url)
                if result:
                    matches = extract_matches(result)
                    print(f"[INFO] Dapat {len(matches)} match dari {url}")
                    all_matches.extend(matches)
                else:
                    print(f"[FAIL] cannot fetch {url}")

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


if __name__ == "__main__":
    asyncio.run(main())
