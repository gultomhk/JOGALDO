import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlparse
import re
import base64
from Crypto.Cipher import AES
import sys

# helper log dengan flush
def log(msg):
    print(msg, flush=True)

# Path ke file config
CONFIG_FILE = Path.home() / "sterame3data_file.txt"

# --- Load konfigurasi dari file ---
config_globals = {}
with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)

# Assign variabel dari config
MATCHES_URL = config_globals.get("MATCHES_URL")
STREAM_URL = config_globals.get("STREAM_URL")
HEADERS = config_globals.get("HEADERS")
PROXY_LIST_URL = config_globals.get("PROXY_LIST_URL")

EXEMPT_CATEGORIES = ["fight", "motor-sports", "tennis"]

# ----------------- Embedsports Extractor -----------------
class Embedsports:
    def __init__(self, proxy=None):
        self.base = "https://embedsports.top"
        self.session = requests.Session()
        self.session.headers.update({
            "Origin": self.base,
            "Referer": self.base,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        if proxy:
            self.session.proxies.update({
                "http": proxy,
                "https": proxy,
            })

    def _pkcs7_unpad(self, data: bytes) -> bytes:
        pad_len = data[-1]
        return data[:-pad_len]

    def _decrypt(self, ciphertext_b64, key_b64, iv_b64):
        key = base64.b64decode(key_b64)
        iv = base64.b64decode(iv_b64)
        ct = base64.b64decode(ciphertext_b64)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(ct)
        return self._pkcs7_unpad(decrypted).decode("utf-8")

    def get_link(self, embed_url: str) -> str:
        m = re.search(r"/embed/([^/]+)/([^/]+)/(\d+)", embed_url)
        if not m:
            raise ValueError("embed_url tidak valid")

        stream_sc, stream_id, stream_no = m.groups()
        payload = {
            "streamId": stream_id,
            "streamNo": int(stream_no),
            "streamType": "live",
            "streamSc": stream_sc,
        }

        resp = self.session.post(self.base + "/fetch", json=payload, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        if "data" not in data or "key" not in data or "iv" not in data:
            raise ValueError("respon tidak lengkap dari embedsports")

        return self._decrypt(data["data"], data["key"], data["iv"])


# --------------- Utils -----------------
def load_proxies():
    try:
        resp = requests.get(PROXY_LIST_URL, timeout=15)
        resp.raise_for_status()
        proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
        log(f"🔌 Total proxy terambil: {len(proxies)}")
        return proxies
    except Exception as e:
        log(f"⚠️ Gagal ambil proxy list: {e}")
        return []


def fetch_stream(source_type, source_id):
    try:
        url = STREAM_URL.format(source_type, source_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        log(f"⚠️ gagal fetch stream {source_type}/{source_id}: {e}")
        return []


# --------------- Main Logic -----------------
async def main(limit_matches=20, apply_time_filter=True):
    log("🚀 Mulai cinhodal1.py")

    try:
        log(f"🌐 Fetch {MATCHES_URL}")
        res = requests.get(MATCHES_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        matches = res.json()
        log(f"✅ Ambil {len(matches)} matches dari API")
    except Exception as e:
        log(f"⛔ Gagal ambil MATCHES_URL: {e}")
        return

    now = datetime.datetime.now(ZoneInfo("Asia/Jakarta"))

    filtered_matches = []
    for match in matches:
        start_at = match["date"] / 1000
        event_time_utc = datetime.datetime.fromtimestamp(start_at, ZoneInfo("UTC"))
        event_time_local = event_time_utc.astimezone(ZoneInfo("Asia/Jakarta"))

        category = match.get("category", "").lower()
        if apply_time_filter and category not in EXEMPT_CATEGORIES:
            if event_time_local < (now - datetime.timedelta(hours=2)):
                continue
        filtered_matches.append(match)

    log(f"📊 Total match terpilih: {len(filtered_matches)}")

    results = {}

    # Step 1: parallel fetch stream metadata
    with ThreadPoolExecutor(max_workers=10) as executor:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, fetch_stream, src["source"], src["id"])
            for match in filtered_matches[:limit_matches]
            for src in match.get("sources", [])
        ]
        streams_list = await asyncio.gather(*tasks)

    # Step 2: pilih proxy dengan embed pertama
    proxies = load_proxies()
    working_proxy = None

    first_embed = None
    for streams in streams_list:
        if streams and streams[0].get("embedUrl"):
            first_embed = streams[0]["embedUrl"]
            break

    if not first_embed:
        log("⚠️ Tidak ada embed ditemukan untuk tes proxy")
        return

    log(f"🎯 Embed pertama untuk tes: {first_embed}")

    for p in proxies:
        try:
            log(f"🔎 Tes proxy {p}")
            es_test = Embedsports(proxy=p)
            _ = es_test.get_link(first_embed)
            log(f"✅ Proxy OK: {p}")
            working_proxy = p
            break
        except Exception as e:
            log(f"❌ Proxy {p} gagal: {e}")

    if not working_proxy:
        log("⛔ Tidak ada proxy yang berhasil, hentikan proses.")
        return

    es = Embedsports(proxy=working_proxy)

    # Step 3: proses hasil API + embed resolver
    for (src, streams) in zip(
        [s for m in filtered_matches[:limit_matches] for s in m.get("sources", [])],
        streams_list,
    ):
        source_type, source_id = src["source"], src["id"]

        if not streams:
            continue

        stream = streams[0]
        stream_no = stream.get("streamNo", 1)
        key = f"{source_type}/{source_id}/{stream_no}"

        url = stream.get("file") or stream.get("url")
        if url:
            results[key] = url
            log(f"[+] API {key} → {url}")
            continue

        embed = stream.get("embedUrl")
        if not embed:
            continue

        host = urlparse(embed).hostname or ""
        if "embedsports.top" in host:
            try:
                link = es.get_link(embed)
                results[key] = link
                log(f"[+] Embedsports {key} → {link}")
            except Exception as e:
                log(f"⚠️ gagal extract {key} dari {embed}: {e}")
        else:
            log(f"❌ Embed {key} host {host} belum didukung")

    # Step 4: simpan hasil ke map5.json
    with open("map5.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log(f"\n✅ Disimpan {len(results)} stream ke map5.json")


if __name__ == "__main__":
    asyncio.run(main())
