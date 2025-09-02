import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import tz
from pathlib import Path
import re
import json
import requests
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
now = datetime.now(tz.gettz("Asia/Jakarta"))

# ========= Parser player?link= → nilai link (ENCODED) + extra params =========
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

# ========= Ekstraksi M3U8 (HTML & iframe) =========
def extract_m3u8_urls(html, base_url=BASE_URL):
    """Ekstrak URL m3u8 dari HTML dengan follow iframe/player untuk ambil authkey"""
    soup = BeautifulSoup(html, "html.parser")
    data_links = soup.select("[data-link]")
    m3u8_urls = []

    for tag in data_links:
        raw = tag.get("data-link", "")
        if not raw:
            continue

        # --- Kasus langsung ---
        if raw.endswith(".m3u8") and raw.startswith("http"):
            print(f"   🔗 Data-link langsung: ✅ {raw}")
            m3u8_urls.append(raw)

        # --- Kasus iframe/player ---
        elif "/player?link=" in raw:
            iframe_url = urljoin(base_url, raw)
            print(f"   🌐 Cek iframe: {iframe_url}")
            try:
                r = requests.get(iframe_url, headers={"User-Agent": USER_AGENT}, timeout=10)
                if r.ok:
                    iframe_html = r.text
                    found = re.findall(r"https?://[^\s\"']+\.m3u8[^\s\"']*", iframe_html)
                    if found:
                        for f in found:
                            if any(k in f for k in ["auth", "token", "key="]):
                                print(f"   🔑 Dari iframe (authkey): ✅ {f}")
                                m3u8_urls.append(f)
                            else:
                                print(f"   ⚠️ Dari iframe tanpa auth: {f}")
                else:
                    print(f"   ❌ Gagal load iframe: {r.status_code}")
            except Exception as e:
                print(f"   ❌ Error iframe fetch: {e}")

        else:
            print(f"   ⚠️ Skip: {raw}")

    return m3u8_urls

# ========= Ambil daftar slug =========
def extract_slug(row):
    if row.has_attr("onclick"):
        match = re.search(r"/match/([^\"']+)", row["onclick"])
        if match:
            return match.group(1).strip()
    link = row.select_one("a[href^='/match/']")
    if link:
        return link['href'].replace('/match/', '').strip()
    return None

def extract_slugs_from_html(html, hours_threshold=2):
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")
    slugs = []
    seen = set()
    now = datetime.now(tz=tz.gettz("Asia/Jakarta"))

    for row in matches:
        try:
            slug = extract_slug(row)
            if not slug or slug in seen:
                continue

            waktu_tag = row.select_one(".match-time")
            if waktu_tag and waktu_tag.get("data-timestamp"):
                timestamp = int(waktu_tag["data-timestamp"])
                event_time_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                event_time_local = event_time_utc.astimezone(tz.gettz("Asia/Jakarta"))
            else:
                event_time_local = now

            is_live = row.select_one(".live-text") is not None

            if not is_live and event_time_local < (now - timedelta(hours=hours_threshold)):
                print(f"⏩ Lewat waktu & bukan live, skip: {slug}")
                continue

            slug_lower = slug.lower()
            is_exception = any(
                keyword in slug_lower
                for keyword in ["tennis", "billiards", "snooker", "worldssp", "superbike"]
            )
            if not is_live and not is_exception and event_time_local < (now - timedelta(hours=hours_threshold)):
                continue

            seen.add(slug)
            slugs.append(slug)

        except Exception as e:
            print(f"❌ Gagal parsing row: {e}")
            continue

    print(f"📦 Total slug valid: {len(slugs)}")
    return slugs

# ========= Pembersih hasil URL =========
def clean_m3u8_links(urls, keep_encoded=True):
    cleaned = []
    seen = set()
    for u in urls:
        if "player?link=" in u:
            u = parse_player_link(u, keep_encoded=keep_encoded)
        if (
            ".m3u8" in u
            and "404" not in u
            and "google.com" not in u
            and "adexchangeclear" not in u
            and u not in seen
        ):
            cleaned.append(u)
            seen.add(u)
    return cleaned

# ========= Playwright fetch m3u8 per slug (FINAL MULTI SERVER, FIXED + LOG) =========
async def fetch_m3u8_with_playwright(context, slug, keep_encoded=True):
    main_url = f"{BASE_URL}/match/{slug}"
    results = {}

    page = await context.new_page()
    try:
        await page.goto(main_url, timeout=30000, wait_until="domcontentloaded")

        # extract tombol jadi data statis
        buttons = await page.query_selector_all(".list-server button[data-link]")
        if not buttons:
            print(f"❌ Tidak ada tombol server di {slug}")
            return results

        server_buttons = []
        for idx, btn in enumerate(buttons, start=1):
            try:
                name = (await btn.inner_text() or f"server{idx}").strip().replace(" ", "_")
                link = await btn.get_attribute("data-link")
                if link:
                    server_buttons.append((name, urljoin(BASE_URL, link)))
            except:
                continue

        # loop data tombol → langsung buka url iframe
        for idx, (name, server_url) in enumerate(server_buttons, start=1):
            print(f"      ▶️ Proses {slug} server{idx} ({name}) → {server_url}")

            iframe_page = await context.new_page()
            m3u8_links = []

            def handle_response(response):
                resp_url = response.url
                if resp_url.endswith(".m3u8") or ".m3u8?" in resp_url:
                    if not any(bad in resp_url for bad in ["404", "google.com", "adexchangeclear"]):
                        m3u8_links.append(resp_url)

            iframe_page.on("response", handle_response)

            try:
                await iframe_page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
                await iframe_page.wait_for_timeout(5000)
            except Exception as e:
                print(f"      ⚠️ Gagal buka server {name}: {e}")
            finally:
                await iframe_page.close()

            if m3u8_links:
                key = slug if idx == 1 else f"{slug}_{name}"
                results[key] = m3u8_links[-1]  # ambil terakhir
                print(f"   ✅ M3U8 ditemukan ({key}): {results[key]}")
            else:
                print(f"      ⚠️ Tidak ada m3u8 di {name}")

    except Exception as e:
        print(f"   ❌ Error buka main slug {slug}: {e}")
    finally:
        await page.close()

    return results
	
# ========= Ambil semua slug parallel =========
async def fetch_all_parallel(slugs, concurrency=5, keep_encoded=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(slug):
            async with semaphore:
                try:
                    # return dict langsung
                    return await fetch_m3u8_with_playwright(
                        context, slug, keep_encoded=keep_encoded
                    )
                except Exception as e:
                    print(f"❌ Error di slug {slug}: {e}")
                    return {}

        # kumpulkan semua task paralel
        tasks = [sem_task(slug) for slug in slugs]
        results = await asyncio.gather(*tasks)
        await browser.close()

        all_data = {}
        for urls_dict in results:
            if not urls_dict:
                continue

            # merge dict hasil ke all_data
            for key, url in urls_dict.items():
                all_data[key] = url
                print(f"   ✅ M3U8 ditemukan ({key}): {url}", flush=True)

        return all_data
		
# ========= Simpan ke map2.json =========
def save_map_file(data):
    with MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ map2.json berhasil disimpan! Total entri: {len(data)}")

# ===== MAIN =====
if __name__ == "__main__":
    html_path = Path("BODATTV_PAGE_SOURCE.html")
    if not html_path.exists():
        raise FileNotFoundError("❌ File HTML tidak ditemukan")

    html = html_path.read_text(encoding="utf-8")
    slug_list = extract_slugs_from_html(html)

    all_data = asyncio.run(fetch_all_parallel(slug_list, concurrency=8, keep_encoded=True))
    save_map_file(all_data)
