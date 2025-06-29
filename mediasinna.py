from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from pathlib import Path
import datetime
from zoneinfo import ZoneInfo

# Path to config
MEDIASDATA_FILE = Path.home() / "mediasdata_file.txt"

def load_config(filepath):
    config = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip().strip('"')
    return config

config = load_config(MEDIASDATA_FILE)

DEFAULT_URL = config["DEFAULT_URL"]
WORKER_URL_TEMPLATE = config["WORKER_URL"]
LOGO = config["LOGO"]
BASE_REFERER = config["BASE_REFERER"]

USER_AGENT = "Mozilla/5.0 AppleWebKit/537.36 Chrome/81.0.4044.138 Safari/537.36"

def translate_vi_to_id(text):
    translations = {
        "Giải Cỏ:": "", "Nga": "Rusia", "Anh": "Inggris", "Đài Loan": "Taiwan",
        "Ngoại Hạng Đan Mạch": "Liga Denmark", "VĐQG Ý": "Serie A Italia", "Áo": "Austria",
        "VĐQG Đức": "Bundesliga", "La Liga": "La Liga Spanyol", "Ấn Độ": "India", "Mông cổ": "Mongolia", "Mỹ": "Amerika",
        "Hạng Nhì Tây Ban Nha": "Segunda División Spanyol", "Na Uy": "Norwegia", "Đức": "Jerman",
        "VĐQG Pháp": "Ligue 1 Prancis", "Cúp C1": "Liga Champions UEFA", "Nam Phi": "Afrika Selatan",
        "Cúp C2": "Liga Eropa UEFA", "Giao hữu": "Laga Persahabatan", "Thụy Sĩ": "Swiss", "Đan Mạch": "Denmark",
        "V-League": "V-League Vietnam", "AFC Champions League": "Liga Champions Asia",
        "Hà Lan": "Belanda", "Bồ Đào Nha": "Portugal", "Bóng chuyền": "Bola voli", "Phần Lan": "Finlandia",
        "Hạng 2": "Liga 2", "Ngoại Hạng": "Liga Primer", "Cúp": "Piala", "Xê Út": "Arab Saudi",
        "VĐQG Brazil": "Serie A Brasil", "VĐQG Argentina": "Liga Argentina", "Triều Tiên": "Terpilih",
        "VĐQG Bulgaria": "Liga Bulgaria", "Hạng hai": "Liga 2", "VĐQG": "Liga", "Đài Loan": "Taiwan",
        "Hạng nhất": "Devisi 1", "Ả Rập": "Arab", "Thụy Điển": "Swedia", "Ấn Độ": "India",
        "Hàn Quốc": "Korea", "nữ": "Putri", "Trung Quốc": "Cina", "Mở Rộng": "terbuka",
        "Bóng chuyền nam": "Bola voli putra", "Bóng chuyền nữ": "Bola voli putri",
        "Bóng rổ": "Bola basket", "Nhật Bản": "Jepang", "Hạng Nhì": "Liga 2",
        "Ba Lan": "Polandia", "Hy Lạp": "Yunani", "Ai Cập": "Mesir", "Pháp": "Perancis", "Giải Tennis": "Turnamen Tenis",
        "Tây Ban Nha": "Spanyol", "Bỉ": "Belgia", "Thổ Nhĩ Kỳ": "Turki", "Đài Bắc Trung Hoa": "Cina Taipei", "Đài Bắc Trung hoa": "Taipei",
    }
    for vi, idn in translations.items():
        text = text.replace(vi, idn)
    return text.strip()

def fetch_m3u_with_playwright():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(DEFAULT_URL, timeout=60000)
        page.wait_for_selector(".box_02.click")

        html = page.content()
        browser.close()

    # Simpan ke file debug
    with open("page.html", "w", encoding="utf-8") as f:
        f.write(html)

    soup = BeautifulSoup(html, "html.parser")
    output = ["#EXTM3U\n"]
    seen = set()

    match_boxes = soup.select(".box_02.click")
    print(f"Found {len(match_boxes)} match boxes")

    for box in match_boxes:
        match_id = box.get("link", "").split("-")[-1].replace(".html", "")
        if not match_id:
            print("Missing match_id, skipped")
            continue

        clubs = box.select(".club .name")
        if len(clubs) != 2:
            print("Incomplete club info, skipped")
            continue

        team_a = translate_vi_to_id(clubs[0].text.strip())
        team_b = translate_vi_to_id(clubs[1].text.strip())

        parent_li = box.find_parent("li")
        time_raw = parent_li.select_one(".box_01 .date")
        if not time_raw:
            print("Missing date info, skipped")
            continue

        date_time_str = time_raw.text.strip().replace(" ", "")

        try:
            current_year = datetime.datetime.now().year
            event_time = datetime.datetime.strptime(f"{date_time_str}-{current_year}", "%H:%M-%d/%m-%Y")
            event_time = event_time.replace(tzinfo=ZoneInfo("UTC"), second=0, microsecond=0)
            wib_time = event_time.astimezone(ZoneInfo("Asia/Jakarta"))
            formatted_time = wib_time.strftime("%d/%m-%H.%M")
        except Exception as time_err:
            print(f"⏰ Error parsing time '{date_time_str}': {time_err}")
            continue

        title = f"{formatted_time} {team_a} vs {team_b}"
        if title in seen:
            continue
        seen.add(title)

        stream_url = WORKER_URL_TEMPLATE.format(match_id=match_id)

        m3u_block = f'''#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO}",{title}
#EXTVLCOPT:http-user-agent={USER_AGENT}
#EXTVLCOPT:http-referrer={BASE_REFERER}
{stream_url}\n'''

        output.append(m3u_block)

    return "".join(output)

if __name__ == "__main__":
    print(fetch_m3u_with_playwright())
