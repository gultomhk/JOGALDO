import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
from deep_translator import GoogleTranslator
from pathlib import Path


# ==========================
# Load Config dari chinzyaigodata_file.txt
# ==========================
CHINZYAIGODATA_FILE = Path.home() / "chinzyaigodata_file.txt"

config_vars = {}
with open(CHINZYAIGODATA_FILE, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, config_vars)

BASE_URL = config_vars.get("BASE_URL")
WORKER_URL = config_vars.get("WORKER_URL")
LOGO_URL = config_vars.get("LOGO_URL")



TARGET_URL = BASE_URL  # langsung halaman utama

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Referer": BASE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

async def translate_zh_to_en(text):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='zh-CN', target='en').translate(text)
    except Exception as e:
        print(f"Translate error for '{text}': {e}")
        return text

async def fetch_html(session, url):
    try:
        async with session.get(url, headers=HEADERS, ssl=False, timeout=15) as response:
            return await response.text()
    except Exception as e:
        print(f"Fetch error: {e}")
        return ""

async def parse_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    lines = []

    # Cek ada <a class="clearfix"> di halaman
    a_tags = soup.select("a.clearfix")
    if not a_tags:
        print("⚠️ No matches found in the HTML.")
        return lines

    for a_tag in a_tags:
        match_url = a_tag.get("href", "")
        if not match_url:
            continue
        match_id = match_url.rstrip("/").split("/")[-1]

        section = a_tag.find("section", class_="jiabifeng")
        if not section:
            continue

        # Tim home & away
        home_div = section.find("div", class_="team zhudui")
        away_div = section.find("div", class_="team kedui")
        home_team = home_div.p.text.strip() if home_div and home_div.p else ""
        away_team = away_div.p.text.strip() if away_div and away_div.p else ""

        # Translate nama tim
        home_team_en = await translate_zh_to_en(home_team)
        away_team_en = await translate_zh_to_en(away_team)

        # Skor
        score_div = section.find("div", class_="bifeng")
        scores = score_div.get_text(separator=":").strip() if score_div else "vs"

        # Liga & waktu
        center_div = section.find("div", class_="center")
        if center_div:
            liga_tag = center_div.find("p", class_="eventtime_wuy")
            liga_name = liga_tag.find("em").text.strip() if liga_tag and liga_tag.find("em") else ""
            event_time = liga_tag.find("i").text.strip() if liga_tag and liga_tag.find("i") else ""
        else:
            liga_name = ""
            event_time = ""

        data_time = a_tag.get("data-time", "")
        try:
            dt_obj = datetime.strptime(f"{data_time} {event_time}", "%Y-%m-%d %H:%M")
            dt_str = dt_obj.strftime("%d/%m-%H.%M")
        except:
            dt_str = f"{data_time}-{event_time}"

        # Format M3U
        title = f"{home_team_en} vs {away_team_en} ({liga_name})"
        lines.append(f'#EXTINF:-1 group-title="⚽️| LIVE EVENT" tvg-logo="{LOGO_URL}", {dt_str} {title}')
        lines.append(f'#EXTVLCOPT:http-user-agent={HEADERS["User-Agent"]}')
        lines.append(f'#EXTVLCOPT:http-referrer={BASE_URL}')
        lines.append(f"{WORKER_URL}{match_id}")

    return lines

async def main():
    async with aiohttp.ClientSession() as session:
        html = await fetch_html(session, TARGET_URL)
        if not html:
            print("⚠️ Failed to fetch HTML. Exiting.")
            return

        lines = await parse_matches(html)

    if lines:
        with open("CHINZYAGIO_.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            f.write("\n".join(lines))
        print(f"✅ Total matches parsed: {len(lines)//4}")
    else:
        print("⚠️ No match entries to write.")

if __name__ == "__main__":
    asyncio.run(main())
