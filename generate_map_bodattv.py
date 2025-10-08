#!/usr/bin/env python3
import asyncio
from bs4 import BeautifulSoup
from pathlib import Path
import re
import json
from urllib.parse import urlparse, parse_qs, unquote, urljoin, urlencode
from playwright.async_api import async_playwright

# ========= Konfigurasi =========
CONFIG_FILE = Path.home() / "bodattvdata_file.txt"
MAP_FILE = Path("map2.json")

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
BASE_URL = config["BASE_URL"]
USER_AGENT = config["USER_AGENT"]

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

    # hapus duplikat
    final = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            final.append(u)
    return final

# ========= Ekstraksi semua slug dari halaman daftar =========
def extract_slugs_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    slugs = set()

    # ambil dari onclick
    for div in soup.select("div.common-table-row.table-row[onclick]"):
        onclick = div.get("onclick", "")
        match = re.search(r"/match/([\w\-\d]+)", onclick)
        if match:
            slug = match.group(1).strip()
            print(f"🎯 Slug (onclick): {slug}")
            slugs.add(slug)

    # ambil dari href
    for a in soup.select("a[href*='/match/']"):
        href = a["href"]
        match = re.search(r"/match/([\w\-\d]+)", href)
        if match:
            slug = match.group(1).strip()
            if slug not in slugs:
                print(f"🎯 Slug (href): {slug}")
                slugs.add(slug)

    print(f"📦 Total slug valid: {len(slugs)}")
    return list(slugs)

# ========= Playwright fetch =========
async def fetch_m3u8_with_playwright(context, slug):
    url = f"{BASE_URL}/match/{slug}"
    page = await context.new_page()
    m3u8_links = []

    def handle_response(response):
        if ".m3u8" in response.url and response.url not in m3u8_links:
            print(f"🎯 [Network] {response.url}")
            m3u8_links.append(response.url)

    page.on("response", handle_response)

    print(f"⚙️ Memproses slug: {slug}")
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)

        html = await page.content()
        found = extract_m3u8_from_match_page(html)
        for f in found:
            if f not in m3u8_links:
                m3u8_links.append(f)
    except Exception as e:
        print(f"❌ Error saat buka slug {slug}: {e}")
    finally:
        await page.close()

    return slug, m3u8_links[0] if m3u8_links else None

# ========= Jalankan semua slug =========
async def fetch_all_parallel(slugs, concurrency=4):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        sem = asyncio.Semaphore(concurrency)

        async def run_one(slug):
            async with sem:
                return await fetch_m3u8_with_playwright(context, slug)

        results = await asyncio.gather(*(run_one(s) for s in slugs))
        await browser.close()

    data = {slug: url for slug, url in results if url}
    return data

# ========= Save JSON =========
def save_map(data):
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Disimpan ke {MAP_FILE} ({len(data)} entri)")

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
        if not slugs:
            print("⚠️ Tidak ada slug ditemukan di HTML.")
        else:
            data = asyncio.run(fetch_all_parallel(slugs))
            save_map(data)
