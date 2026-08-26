import requests
from bs4 import BeautifulSoup
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib3
import json
import sys

# =========================================================
# ARGOS PACKAGE
# =========================================================

ARGOS_INDEX_URL = (
    "https://raw.githubusercontent.com/"
    "argosopentech/argospm-index/main/index.json"
)

ARGOS_FROM = "vi"
ARGOS_TO = "en"

# =========================================================
# IMPORT ARGOS
# =========================================================

try:
    import argostranslate.package
    import argostranslate.translate
except ImportError:
    print("❌ Argos Translate belum terinstall.")
    print()
    print("Install dengan:")
    print("pip install argostranslate")
    sys.exit(1)


urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# LOAD KONFIGURASI
# =========================================================

CONFIG_FILE = Path.home() / "keongdata.txt"

if not CONFIG_FILE.exists():
    print(f"❌ File konfigurasi tidak ditemukan: {CONFIG_FILE}")
    sys.exit(1)

config_globals = {}

with open(CONFIG_FILE, encoding="utf-8") as f:
    exec(f.read(), config_globals)


def clean_value(val):
    return val.strip() if isinstance(val, str) else val


BASE_URL = clean_value(
    config_globals.get("BASE_URL")
)

TABS = config_globals.get(
    "TABS",
    []
)

USER_AGENT = clean_value(
    config_globals.get("USER_AGENT")
)

REFERRER = clean_value(
    config_globals.get("REFERRER")
)

LOGO_URL = clean_value(
    config_globals.get("LOGO_URL")
)

MY_WEBSITE = clean_value(
    config_globals.get("MY_WEBSITE")
)

CF_CLEARANCE = clean_value(
    config_globals.get("CF_CLEARANCE")
)


# =========================================================
# SESSION
# =========================================================

session = requests.Session()

session.verify = False

session.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": REFERRER,
    "Accept": "text/html,application/xhtml+xml;q=0.9",
})

if CF_CLEARANCE:
    session.cookies.set(
        "cf_clearance",
        CF_CLEARANCE
    )


# =========================================================
# PROXIED GET
# =========================================================

def proxied_get(url, timeout=15, **kwargs):
    return session.get(
        url,
        timeout=timeout,
        **kwargs
    )


# =========================================================
# ARGOS - UPDATE INDEX
# =========================================================

def update_argos_index():
    """
    Download index.json Argos secara langsung
    dari ARGOS_INDEX_URL.

    Kita tidak bergantung pada Google Translate
    dan tidak bergantung pada API download_package
    yang berbeda-beda antar versi Argos.
    """

    print()
    print("🌐 Mengambil Argos package index...")
    print(f"   {ARGOS_INDEX_URL}")

    try:
        response = requests.get(
            ARGOS_INDEX_URL,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            raise ValueError(
                "Format Argos index bukan list."
            )

        print(
            f"✅ Argos index berhasil: {len(data)} package"
        )

        return data

    except Exception as e:
        print(
            f"❌ Gagal mengambil Argos index: {e}"
        )
        return []


# =========================================================
# ARGOS - FIND PACKAGE
# =========================================================

def find_argos_package(index_data, from_code, to_code):

    for item in index_data:

        if not isinstance(item, dict):
            continue

        item_from = item.get("from_code")
        item_to = item.get("to_code")

        if (
            item_from == from_code
            and item_to == to_code
        ):
            return item

    return None


# =========================================================
# ARGOS - DOWNLOAD PACKAGE MANUAL
# =========================================================

def download_argos_package(package_data):

    links = package_data.get("links", [])

    if not links:
        print("❌ Package Argos tidak mempunyai links.")
        return None

    # Ambil link pertama yang valid
    package_url = None

    for link in links:

        if isinstance(link, str):
            if link.startswith("http"):
                package_url = link
                break

        elif isinstance(link, dict):

            # beberapa versi index bisa mempunyai
            # struktur dictionary
            for key in ("url", "link", "download"):

                value = link.get(key)

                if (
                    isinstance(value, str)
                    and value.startswith("http")
                ):
                    package_url = value
                    break

            if package_url:
                break

    if not package_url:
        print("❌ URL package Argos tidak ditemukan.")
        return None

    print()
    print("📦 Argos package ditemukan:")
    print(
        f"   {package_data.get('from_code')} "
        f"→ "
        f"{package_data.get('to_code')}"
    )

    print(
        f"⬇️ Download: {package_url}"
    )

    try:

        response = requests.get(
            package_url,
            timeout=120,
            stream=True
        )

        response.raise_for_status()

        # Gunakan cache directory
        cache_dir = (
            Path.home()
            / ".argos_cache"
        )

        cache_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        package_version = (
            package_data.get(
                "package_version",
                "latest"
            )
        )

        filename = (
            f"translate-{ARGOS_FROM}_"
            f"{ARGOS_TO}-{package_version}.argosmodel"
        )

        package_path = cache_dir / filename

        # Jangan download ulang jika sudah ada
        if package_path.exists():
            print(
                f"📁 Package sudah ada:"
                f" {package_path}"
            )

            return package_path

        with open(
            package_path,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:
                    f.write(chunk)

        print(
            f"✅ Package tersimpan:"
            f" {package_path}"
        )

        return package_path

    except Exception as e:

        print(
            f"❌ Download Argos gagal: {e}"
        )

        return None


# =========================================================
# ARGOS - INSTALL PACKAGE
# =========================================================

def install_argos_package(package_path):

    if not package_path:
        return False

    try:

        print()
        print("📦 Memasang Argos package...")

        argostranslate.package.install_from_path(
            package_path
        )

        print(
            "✅ Argos package berhasil dipasang."
        )

        return True

    except Exception as e:

        print(
            f"❌ Instalasi Argos gagal: "
            f"{type(e).__name__}: {e}"
        )

        return False


# =========================================================
# ARGOS - CHECK INSTALLED
# =========================================================

def argos_pair_installed(
    from_code="vi",
    to_code="en"
):

    try:

        languages = (
            argostranslate.translate
            .get_installed_languages()
        )

        from_lang = next(
            (
                lang
                for lang in languages
                if lang.code == from_code
            ),
            None
        )

        to_lang = next(
            (
                lang
                for lang in languages
                if lang.code == to_code
            ),
            None
        )

        if not from_lang or not to_lang:
            return False

        # Jangan menggunakan .translations
        # karena versi Argos tertentu tidak
        # mempunyai attribute tersebut.

        try:

            translation = (
                from_lang.get_translation(
                    to_lang
                )
            )

            return translation is not None

        except Exception:

            return False

    except Exception:

        return False


# =========================================================
# ARGOS - INITIALIZE
# =========================================================

def initialize_argos():

    print()
    print("=" * 60)
    print("ARGOS TRANSLATE")
    print("=" * 60)

    # -----------------------------------------------------
    # 1. Cek apakah vi -> en sudah terpasang
    # -----------------------------------------------------

    if argos_pair_installed(
        ARGOS_FROM,
        ARGOS_TO
    ):

        print(
            "✅ Model vi → en sudah tersedia."
        )

        return True

    print(
        "⚠️ Model vi → en belum tersedia."
    )

    # -----------------------------------------------------
    # 2. Ambil index
    # -----------------------------------------------------

    index_data = update_argos_index()

    if not index_data:
        return False

    # -----------------------------------------------------
    # 3. Cari package vi -> en
    # -----------------------------------------------------

    package_data = find_argos_package(
        index_data,
        ARGOS_FROM,
        ARGOS_TO
    )

    if not package_data:

        print(
            "❌ Package vi → en tidak ditemukan "
            "di Argos index."
        )

        return False

    # -----------------------------------------------------
    # 4. Download
    # -----------------------------------------------------

    package_path = download_argos_package(
        package_data
    )

    if not package_path:
        return False

    # -----------------------------------------------------
    # 5. Install
    # -----------------------------------------------------

    if not install_argos_package(
        package_path
    ):
        return False

    # -----------------------------------------------------
    # 6. Verify
    # -----------------------------------------------------

    if argos_pair_installed(
        ARGOS_FROM,
        ARGOS_TO
    ):

        print(
            "✅ Model vi → en siap digunakan."
        )

        return True

    print(
        "❌ Model terpasang tetapi "
        "vi → en tidak terdeteksi."
    )

    return False


# =========================================================
# ARGOS TRANSLATOR
# =========================================================

ARGOS_READY = False
ARGOS_TRANSLATOR = None

# Cache supaya title yang sama tidak diterjemahkan ulang
TRANSLATION_CACHE = {}


def setup_translator():

    global ARGOS_READY
    global ARGOS_TRANSLATOR

    if not initialize_argos():

        print(
            "⚠️ Argos tidak tersedia."
        )

        print(
            "⚠️ Title akan tetap menggunakan "
            "bahasa asli."
        )

        ARGOS_READY = False
        return

    try:

        languages = (
            argostranslate.translate
            .get_installed_languages()
        )

        from_lang = next(
            (
                lang
                for lang in languages
                if lang.code == ARGOS_FROM
            ),
            None
        )

        to_lang = next(
            (
                lang
                for lang in languages
                if lang.code == ARGOS_TO
            ),
            None
        )

        if not from_lang or not to_lang:

            raise RuntimeError(
                "Bahasa vi/en tidak ditemukan."
            )

        ARGOS_TRANSLATOR = (
            from_lang.get_translation(
                to_lang
            )
        )

        if ARGOS_TRANSLATOR is None:

            raise RuntimeError(
                "Translation model vi → en "
                "tidak ditemukan."
            )

        ARGOS_READY = True

        print(
            "✅ Translator Argos vi → en aktif."
        )

    except Exception as e:

        print(
            f"❌ Gagal membuat translator: "
            f"{type(e).__name__}: {e}"
        )

        ARGOS_READY = False
        ARGOS_TRANSLATOR = None


# =========================================================
# TRANSLATE TITLE ONLY
# =========================================================

def translate_title(text):

    if not text:
        return text

    text = text.strip()

    if not text:
        return text

    # Jangan translate jika Argos tidak tersedia
    if not ARGOS_READY or ARGOS_TRANSLATOR is None:
        return text

    # Cache
    cache_key = text.lower()

    if cache_key in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[cache_key]

    try:

        translated = (
            ARGOS_TRANSLATOR.translate(text)
        )

        if not translated:
            return text

        translated = translated.strip()

        # Simpan cache
        TRANSLATION_CACHE[
            cache_key
        ] = translated

        return translated

    except Exception as e:

        print(
            f"⚠️ Translate gagal "
            f"'{text}': {e}"
        )

        return text


# =========================================================
# MAIN PAGE
# =========================================================

print("🌐 Mengambil halaman utama...")

try:

    resp = session.get(
        BASE_URL,
        timeout=15
    )

    resp.raise_for_status()

except Exception as e:

    print(
        f"❌ Gagal mengambil BASE_URL: {e}"
    )

    sys.exit(1)


soup = BeautifulSoup(
    resp.text,
    "html.parser"
)


# =========================================================
# HELPERS
# =========================================================

def extract_slug(url):

    if not url:
        return ""

    if url.startswith("http"):

        return urlparse(
            url
        ).path.lstrip("/")

    return url.lstrip("/")


def parse_time_from_slug(slug: str):

    m = re.search(
        r"luc-(\d{1,2})(\d{2})-ngay-"
        r"(\d{1,2})-(\d{1,2})-(\d{4})",
        slug
    )

    if m:

        h, mm, d, mo, y = m.groups()

        return (
            f"{int(d):02d}/"
            f"{int(mo):02d}-"
            f"{int(h):02d}."
            f"{mm}"
        )

    return "??/??-??.??"


def clean_text(text):

    if not text:
        return ""

    text = text.replace(",", "")
    text = text.replace(":", "")

    text = re.sub(
        r"\s{2,}",
        " ",
        text
    )

    return text.strip()


def clean_parentheses(text: str):

    def repl(m):

        inner = clean_text(
            m.group(1)
        )

        return f"({inner})"

    return re.sub(
        r"\((.*?)\)",
        repl,
        text
    )


# =========================================================
# PARSE TITLE FROM SLUG
# =========================================================

def parse_title_from_slug(slug: str):

    # -----------------------------------------------------
    # PENTING:
    # Fungsi ini hanya mengambil TITLE dari slug.
    #
    # SLUG ASLI TIDAK PERNAH DIUBAH.
    # -----------------------------------------------------

    title_part = re.sub(
        r"^truc-tiep[-/]*",
        "",
        slug,
        flags=re.IGNORECASE
    )

    title_part = re.sub(
        r"-luc-\d{3,4}-ngay-"
        r"\d{1,2}-\d{1,2}-\d{4}$",
        "",
        title_part,
        flags=re.IGNORECASE
    )

    # slug -> title
    title_part = re.sub(
        r"[-_/]+",
        " ",
        title_part
    ).strip()

    title_part = clean_text(
        title_part
    )

    if not title_part:
        return ""

    # -----------------------------------------------------
    # TRANSLATE TITLE SAJA
    # -----------------------------------------------------

    translated = translate_title(
        title_part
    )

    translated = clean_text(
        translated
    )

    # -----------------------------------------------------
    # Jika hasil translation sama,
    # jangan tambahkan "(hasil sama)"
    # -----------------------------------------------------

    if (
        translated
        and translated.lower()
        != title_part.lower()
    ):

        full_title = (
            f"{title_part} "
            f"({translated})"
        )

    else:

        full_title = title_part

    return clean_parentheses(
        full_title
    )


# =========================================================
# START ARGOS
# =========================================================

setup_translator()


# =========================================================
# PROCESS
# =========================================================

output_lines = [
    "#EXTM3U"
]

seen_full_slugs = set()


for tab_id in TABS:

    tab_section = soup.select_one(
        f"#{tab_id}"
    )

    if not tab_section:

        print(
            f"⚠️ Tab '{tab_id}' tidak ditemukan."
        )

        continue

    print(
        f"✅ Tab '{tab_id}'"
    )

    for a in tab_section.select(
        "a[href*='/truc-tiep/']"
    ):

        href_main = a.get("href")

        if not href_main:
            continue

        full_main_url = urljoin(
            BASE_URL,
            href_main
        )

        try:

            page = session.get(
                full_main_url,
                timeout=15
            )

            page.raise_for_status()

        except Exception as e:

            print(
                f"❌ Gagal: {e}"
            )

            continue

        detail = BeautifulSoup(
            page.text,
            "html.parser"
        )

        tv_links = (
            detail.select(
                "div#tv_links a.player-link"
            )
        )

        # -------------------------------------------------
        # Jika tidak ada player
        # gunakan href utama
        # -------------------------------------------------

        if not tv_links:

            tv_links = [
                {
                    "href": href_main
                }
            ]

        print(
            f"🎬 {len(tv_links)} player"
        )

        for idx, pl in enumerate(
            tv_links
        ):

            if isinstance(pl, dict):

                href_player = pl.get(
                    "href"
                )

            else:

                href_player = pl.get(
                    "href"
                )

            if not href_player:
                continue

            # =================================================
            # SLUG ASLI
            # =================================================

            slug_full = extract_slug(
                href_player
            )

            if not slug_full:
                continue

            # =================================================
            # DUPLICATE CHECK
            # =================================================

            if slug_full in seen_full_slugs:
                continue

            seen_full_slugs.add(
                slug_full
            )

            # =================================================
            # TIME
            # =================================================

            match_time = parse_time_from_slug(
                slug_full
            )

            # =================================================
            # TITLE
            #
            # HANYA TITLE YANG DITERJEMAHKAN
            # =================================================

            title = parse_title_from_slug(
                slug_full
            )

            # =================================================
            # FINAL URL
            #
            # SLUG TETAP ASLI
            # =================================================

            if "?slug=" in MY_WEBSITE:

                final_url = (
                    f"{MY_WEBSITE}"
                    f"{slug_full}"
                )

            else:

                final_url = (
                    f"{MY_WEBSITE}"
                    f"?slug={slug_full}"
                )

            # =================================================
            # PLAYER LABEL
            # =================================================

            if isinstance(pl, dict):

                label = ""

            else:

                label = pl.get_text(
                    strip=True
                )

            label = (
                label
                or f"Server {idx + 1}"
            )

            # =================================================
            # M3U
            # =================================================

            output_lines.append(
                f'#EXTINF:-1 '
                f'group-title="⚽️| LIVE EVENT" '
                f'tvg-logo="{LOGO_URL}",'
                f'{match_time} '
                f'{title} '
                f'[{label}]'
            )

            output_lines.append(
                f"#EXTVLCOPT:"
                f"http-user-agent="
                f"{USER_AGENT}"
            )

            output_lines.append(
                f"#EXTVLCOPT:"
                f"http-referrer="
                f"{REFERRER}"
            )

            output_lines.append(
                final_url
            )


# =========================================================
# SAVE
# =========================================================

filename = "Keongphut_sport.m3u"

with open(
    filename,
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "\n".join(output_lines)
        + "\n"
    )


# =========================================================
# RESULT
# =========================================================

print()
print("=" * 60)
print(
    f"✅ Selesai: {filename}"
)
print(
    f"📺 Total channel: "
    f"{len(seen_full_slugs)}"
)
print(
    f"🌐 Total title translated/cache: "
    f"{len(TRANSLATION_CACHE)}"
)
print("=" * 60)
