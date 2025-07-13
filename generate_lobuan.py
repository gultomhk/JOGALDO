import requests
import re
from pathlib import Path

# Load konfigurasi
config_path = Path.home() / "datarock_file.txt"
with open(config_path, "r", encoding="utf-8") as f:
    config_lines = f.read().splitlines()

def parse_config(lines):
    config = {}
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip().strip('"')
    return config

cfg = parse_config(config_lines)
source_url = cfg.get("source_url")
proxy_list_url = cfg.get("proxy_list_url")
user_agent = cfg.get("user_agent")
redirect_prefixes = [prefix.strip() for prefix in cfg.get("redirect_prefixes", "").split(",") if prefix.strip()]

headers = {"User-Agent": user_agent}

def get_proxy_list():
    try:
        res = requests.get(proxy_list_url, timeout=10)
        res.raise_for_status()
        return [line.strip() for line in res.text.splitlines() if line.strip()]
    except:
        return []

def request_with_proxies(url, proxies, **kwargs):
    for proxy in proxies:
        try:
            proxy_dict = {"http": proxy, "https": proxy}
            res = requests.get(url, headers=headers, proxies=proxy_dict, timeout=10, **kwargs)
            if res.status_code == 200:
                return res
        except:
            continue
    return requests.get(url, headers=headers, timeout=10, **kwargs)

def is_redirect_url(line):
    return any(line.startswith(prefix) for prefix in redirect_prefixes)

def resolve_redirect(url):
    try:
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=10)
        if r.status_code in (301, 302):
            return r.headers.get("Location", url)
    except:
        pass
    return url

def remove_group_logo_attribute(extinf_line):
    return re.sub(r'\s*group-logo="[^"]+"', '', extinf_line)

def process_playlist(source_url):
    proxies = get_proxy_list()
    res = request_with_proxies(source_url, proxies)
    res.raise_for_status()
    lines = res.text.splitlines()

    output_lines = ["#EXTM3U"]
    i = 0
    buffer = []

    found = 0  # counter debug

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        if not line.startswith("#EXTINF"):
            buffer.append(line)
            i += 1
            continue

        if 'group-title="Sports | AstroGO"' in line:
            found += 1
            print(f"[MATCH] ▶ {line}")

            for meta in buffer:
                output_lines.append(meta)

            cleaned_line = remove_group_logo_attribute(line)
            modified_line = cleaned_line.replace('group-title="Sports | AstroGO"', 'group-title="🏎|TV SPORT"')
            output_lines.append(modified_line)
            buffer = []

            i += 1
            while i < len(lines) and not lines[i].strip().startswith("#EXTINF"):
                current_line = lines[i].strip()
                if is_redirect_url(current_line):
                    resolved_url = resolve_redirect(current_line)
                    output_lines.append(resolved_url)
                else:
                    output_lines.append(current_line)
                i += 1
            continue

        buffer = []
        i += 1

    if found == 0:
        print("⚠️ Tidak ditemukan satupun EXTINF dengan group-title=Sports | AstroGO")

    return "\n".join(output_lines)

if __name__ == "__main__":
    result = process_playlist(source_url)
    print(result)
