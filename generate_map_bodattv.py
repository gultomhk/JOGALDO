import re
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

CONFIG_FILE = Path("bodattvdata_file.txt")
MAP_FILE = Path("map2.json")


def load_config():
    """Muat konfigurasi dari bodattvdata_file.txt"""
    config = {}
    current_key = None
    with open(CONFIG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = map(str.strip, line.split("=", 1))
                current_key = key
                config[key] = value
            else:
                config[current_key] += "\n" + line
    config["channel_ids"] = config["channel_ids"].splitlines()
    config["headers"] = json.loads(config["headers"])
    return config


def extract_slug(row):
    """Ambil slug pertandingan dari elemen HTML baris pertandingan"""
    link = row.select_one("a[href^='/match/']")
    if link:
        href = link.get("href", "")
        match = re.search(r"/match/([^/?#]+)", href)
        if match:
            return match.group(1)
    return None


def extract_slugs_from_html(html):
    """Ekstrak semua slug pertandingan dari HTML"""
    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select("div.common-table-row.table-row")
    print(f"📦 Total match ditemukan: {len(matches)}")
    slugs = []
    seen = set()
    for row in matches:
        slug = extract_slug(row)
        if slug and slug not in seen:
            slugs.append(slug)
            seen.add(slug)
    return slugs


def extract_m3u8_urls_from_html(html):
    """Ekstrak URL .m3u8 langsung dan dari iframe"""
    soup = BeautifulSoup(html, "html.parser")
    m3u8_urls = []

    # Ekstrak langsung dari string HTML
    raw_urls = re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', html)
    m3u8_urls.extend(raw_urls)

    # Cek iframe
    for iframe in soup.find_all("iframe"):
        data_link = iframe.get("data-link", "")
        src = iframe.get("src", "")
        for val in (data_link, src):
            if not val:
                continue
            if "/player?link=" in val:
                parsed = urlparse(val)
                query = parse_qs(parsed.query)
                encoded_link = query.get("link", [None])[0]
                if encoded_link:
                    decoded_url = unquote(encoded_link)
                    if ".m3u8" in decoded_url:
                        m3u8_urls.append(decoded_url)
                        print(f"   🔗 Langsung dari iframe (decoded): {decoded_url}")
            elif ".m3u8" in val:
                m3u8_urls.append(val)
                print(f"   🔗 Langsung dari iframe: {val}")

    return list(dict.fromkeys(m3u8_urls))  # unikkan


def fetch_html(url, headers):
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.text
        else:
            print(f"❌ Gagal fetch {url} ({response.status_code})")
    except Exception as e:
        print(f"❌ Error saat fetch {url} - {e}")
    return ""


def process_slug(slug, url_template, headers):
    url = url_template.format(slug=slug)
    html = fetch_html(url, headers)
    if not html:
        return []
    return extract_m3u8_urls_from_html(html)


def main():
    config = load_config()
    headers = config["headers"]
    url_template = config["url_template"]
    source_url = config["source_url"]

    # Fetch halaman utama, ambil semua slug
    html = fetch_html(source_url, headers)
    slugs = extract_slugs_from_html(html)
    print(f"🔍 Slug ditemukan: {len(slugs)}")

    result = {}
    for slug in slugs:
        print(f"\n🔎 Proses slug: {slug}")
        urls = process_slug(slug, url_template, headers)
        if not urls:
            print(f"⚠️  Tidak ada URL ditemukan untuk {slug}")
            continue
        if len(urls) == 1:
            result[slug] = urls[0]
        else:
            for i, url in enumerate(urls, 1):
                key = f"{slug} server{i}"
                result[key] = url

    # Simpan ke file JSON
    with open(MAP_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n✅ Disimpan ke {MAP_FILE} (total: {len(result)} channel)")


if __name__ == "__main__":
    main()
