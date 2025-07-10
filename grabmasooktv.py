import os
import requests
import re

# Ambil dari environment variable
proxy_prefix = os.getenv("PROXY_PREFIX")
source_url_1 = os.getenv("SOURCE_URL_1")
source_url_2 = os.getenv("SOURCE_URL_2")
output_file = "MASSOOKTV.m3u8"

# Validasi env
if not proxy_prefix or not source_url_1 or not source_url_2:
    print("❌ ERROR: PROXY_PREFIX, SOURCE_URL_1, dan SOURCE_URL_2 harus di-set sebagai environment variable.")
    exit(1)

# Ambil data dari kedua sumber
try:
    res1 = requests.get(source_url_1)
    res1.raise_for_status()
    data1 = res1.text.splitlines()

    res2 = requests.get(source_url_2)
    res2.raise_for_status()
    data2 = res2.text.splitlines()
except Exception as e:
    print(f"❌ Gagal ambil data: {e}")
    exit(1)

def extract_sooka_blocks_with_proxy(lines):
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF:") and 'group-title="Sooka ᵒᵗᵗ"' in lines[i]:
            extinf_line = re.sub(r'group-title="[^"]+"', 'group-title="🖥|TV SOOKAMALAYSIA"', lines[i])
            block = []

            # Ambil metadata sebelum EXTINF
            j = i - 1
            while j >= 0 and lines[j].startswith("#") and not lines[j].startswith("#EXTINF:"):
                block.insert(0, lines[j])
                j -= 1

            block.append(extinf_line)
            i += 1

            # Ambil satu URL setelah EXTINF
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("http"):
                    block.append(proxy_prefix + line)
                    break
                elif line.startswith("#"):
                    block.append(line)
                i += 1

            blocks.append(block)
        else:
            i += 1
    return blocks

# Proses semua data
blocks1 = extract_sooka_blocks_with_proxy(data1)
blocks2 = extract_sooka_blocks_with_proxy(data2)

# Gabungkan dan simpan ke file
final_lines = ["#EXTM3U"]
for block in blocks1 + blocks2:
    final_lines.extend(block)

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(final_lines))

print(f"✅ Selesai. Total: {len(blocks1) + len(blocks2)} channel Sooka ditulis ke {output_file} via proxy.")
