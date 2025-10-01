from pathlib import Path
import requests
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any


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

OUT_FILE = "CHIN2_matches.m3u"

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


def normalize_matches(raw) -> List[Dict[str, Any]]:
    """Normalize Worker JSON (list) atau API JSON (dict) jadi format standar."""
    out = []
    if isinstance(raw, list):
        # format dari Worker JSON
        for m in raw:
            iid = m.get("iid")
            home = m.get("home")
            away = m.get("away")
            league = m.get("league", "")
            kickoff_ts = None
            ts = m.get("startTime")
            if ts:
                try:
                    kickoff_ts = int(ts)
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
                    pass
            title = f"{time_str} {home or ''} vs {away or ''} ({league})".strip()
            out.append({
                "iid": str(iid) if iid is not None else None,
                "home": home or "",
                "away": away or "",
                "kickoff": kickoff_ts,
                "title": title,
                "logo": DEFAULT_LOGO,
            })
    elif isinstance(raw, dict):
        # fallback: format API tournament/info
        out.extend(extract_matches(raw))
    return out


def main():
    all_matches = []
    try:
        resp = requests.get(
            WORKER_MATCHES,
            headers={"User-Agent": UA, "Referer": REFERER},
            timeout=15
        )
        if resp.status_code != 200:
            print(f"[ERROR] Worker returned {resp.status_code}")
            return
        raw = resp.json()
        matches = normalize_matches(raw)
        all_matches.extend(matches)
    except Exception as e:
        print(f"[ERROR] Failed to fetch matches from Worker: {e}")
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

    # filter kickoff > 2 jam lewat
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
    main()
