#!/usr/bin/env python3
import asyncio
import os
import json
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright
import re

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

# ========= Load Config =========
def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"❌ File config tidak ditemukan: {CONFIG_FILE}")

config = load_config(CONFIG_FILE)
BASE_URL = config.get("BASE_URL")
USER_AGENT = config.get("USER_AGENT")
HEADLESS = config.get("HEADLESS", "true").lower() != "false"

# ========= Proxy Handling =========
PROXY_LIST_URL = config.get("PROXY_LIST_URL", PROXY_LIST_URL_DEFAULT)
PROXY_URL = config.get("PROXY_URL") or os.environ.get("HTTP_PROXY")

# Cache proxy yang berhasil
working_proxy = None

def get_proxy_list():
    """Ambil daftar proxy dari file eksternal"""
    try:
        print(f"🌐 Mengambil proxy list dari {PROXY_LIST_URL}")
        r = requests.get(PROXY_LIST_URL, timeout=10)
        r.raise_for_status()
        proxies = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith("http"):
                line = "http://" + line
            proxies.append(line)
        print(f"✅ Total proxy terambil: {len(proxies)}")
        return proxies
    except Exception as e:
        print(f"❌ Gagal ambil proxy list: {e}")
        return []


async def get_working_proxy(playwright, test_url=f"https://example.com"):
    """Coba cari proxy yang bisa akses situs (dipakai untuk semua slug berikutnya)"""
    global working_proxy
    proxies = get_proxy_list()
    if not proxies:
        print("⚠️ Tidak ada proxy list tersedia.")
        return None

    for proxy in proxies:
        print(f"▶️ Coba proxy: {proxy}")
        try:
            browser = await playwright.chromium.launch(
                headless=True, args=[f"--proxy-server={proxy}"]
            )
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(test_url, timeout=8000)
            if "Example Domain" in await page.content():
                print(f"✅ Proxy berhasil: {proxy}")
                await browser.close()
                working_proxy = proxy
                return proxy
            await browser.close()
        except Exception as e:
            print(f"❌ Proxy gagal: {e}")
            continue

    print("⚠️ Tidak ada proxy yang valid ditemukan.")
    return None


# ========= Parser player?link= → nilai link =========
def parse_player_link(url: str, keep_encoded: bool = True) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "link" not in qs:
        return url
    encoded_link_value = qs["link"][0]
    extras = {k: v for k, v in qs.items() if k != "link"}
    extra_str = urlencode(extras, doseq=True) if extras else ""
    if keep_encoded:
        return encoded_link_value + (("&" + extra_str) if extra_str else "")
    else:
        decoded = unquote(encoded_link_value)
        if extra_str:
            decoded += "&" + extra_str if "?" in decoded else "?" + extra_str
        return decoded


# ========= Ekstraksi M3U8 dari halaman pertandingan tunggal =========
def extract_m3u8_from_match_page(html):
    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.select_one("iframe[src*='player?link=']")
    btns = soup.select(".btn-server[data-link]")
    urls = []

    if iframe:
        src = iframe.get("src")
        if src:
            full = urljoin(BASE_URL, src)
            parsed = parse_player_link(full)
            urls.append(parsed)
            print(f"✅ Ditemukan iframe utama: {parsed}")

    for b in btns:
        raw = b.get("data-link")
        if raw and ".m3u8" in raw:
            urls.append(raw)
            print(f"✅ Ditemukan tombol server: {raw}")

    return list(dict.fromkeys(urls))


# ========= Ekstraksi slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link["href"].replace("/match/", "").strip()
    return None


def extract_slugs_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    return [extract_slug(row) for row in matches if extract_slug(row)]


# ========= Playwright fetch =========
async def fetch_m3u8_with_playwright(context, slug):
    url = f"{BASE_URL}/match/{slug}"
    print(f"\n⚙️ Memproses slug: {slug}")
    page = await context.new_page()
    m3u8_links = []

    def handle_response(response):
        if ".m3u8" in response.url and response.url not in m3u8_links:
            print(f"🎯 [Network] {slug} → {response.url}")
            m3u8_links.append(response.url)

    page.on("response", handle_response)

    try:
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        await page.wait_for_timeout(7000)
        html = await page.content()
        if "Cloudflare" in html:
            print(f"⚠️ Terblokir Cloudflare: {slug}")
        else:
            found = extract_m3u8_from_match_page(html)
            for f in found:
                if f not in m3u8_links:
                    m3u8_links.append(f)
                    print(f"🎯 [HTML] {slug} → {f}")

        if not m3u8_links:
            Path(f"debug_{slug}.html").write_text(html, encoding="utf-8")
            print(f"💾 Simpan debug_{slug}.html (tidak ada m3u8)")
    except Exception as e:
        print(f"❌ Error {slug}: {e}")
    finally:
        await page.close()

    return slug, m3u8_links[0] if m3u8_links else None


# ========= Jalankan semua slug =========
async def fetch_all_parallel(slugs, concurrency=3):
    global working_proxy
    async with async_playwright() as p:
        # Tentukan proxy yang akan dipakai
        if PROXY_URL:
            proxy_arg = PROXY_URL
            print(f"🌍 Menggunakan proxy dari config: {proxy_arg}")
        else:
            proxy_arg = await get_working_proxy(p)  # auto cari proxy
            print(f"🌍 Proxy otomatis dipilih: {proxy_arg or 'tidak ada'}")

        args = ["--disable-blink-features=AutomationControlled"]
        if proxy_arg:
            args.append(f"--proxy-server={proxy_arg}")

        browser = await p.chromium.launch(headless=HEADLESS, args=args)
        context = await browser.new_context(user_agent=USER_AGENT)

        sem = asyncio.Semaphore(concurrency)
        async def run_one(slug):
            async with sem:
                return await fetch_m3u8_with_playwright(context, slug)

        results = await asyncio.gather(*(run_one(s) for s in slugs))
        await browser.close()

    return {slug: url for slug, url in results if url}


# ========= Save JSON =========
def save_map(data):
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Disimpan ke {MAP_FILE} ({len(data)} entri)")


# ========= MAIN =========
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")

    if "iframe" in html and "btn-server" in html:
        print("📺 Mode: halaman pertandingan tunggal")
        urls = extract_m3u8_from_match_page(html)
        data = {"single_match": urls[0] if urls else None}
        save_map(data)
    else:
        print("📋 Mode: halaman daftar pertandingan")
        slugs = extract_slugs_from_html(html)
        print(f"🔍 Total slug ditemukan: {len(slugs)}")
        data = asyncio.run(fetch_all_parallel(slugs))
        save_map(data)
