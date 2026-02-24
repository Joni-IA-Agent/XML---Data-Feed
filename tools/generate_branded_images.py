"""
generate_branded_images.py — Estropical.com Branded Product Image Generator
============================================================================
Reads .tmp/products_raw.json, downloads each product's source image,
and composites it with:
  • Estropical logo (blue version) — bottom-left of white strip
  • Destination city/country name  — bottom-right of white strip, Persian Blue
  • Professional travel-ad layout matching the brand manual

Output:  docs/images/{product_id}.jpg  (1200 × 628 px)
Manifest: .tmp/image_manifest.json    (product_id → public GitHub Pages URL)

Run:  python tools/generate_branded_images.py
"""

import io
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Config ────────────────────────────────────────────────────────────────────
INPUT_PATH      = Path(".tmp/products_raw.json")
OUTPUT_DIR      = Path("docs/images")
MANIFEST_PATH   = Path(".tmp/image_manifest.json")
CACHE_DIR       = Path(".tmp/img_cache")

# GitHub Pages base URL — update if repo or username changes
GITHUB_PAGES_BASE = "https://joni-ia-agent.github.io/XML---Data-Feed/images"

# Canvas dimensions — square format for Instagram/Meta/TikTok catalog ads
IMG_W, IMG_H    = 1080, 1080
STRIP_H         = 130   # white brand strip at bottom
PHOTO_H         = IMG_H - STRIP_H  # 950 px for the photo

# Brand colours (from brand manual)
PERSIAN_BLUE    = (29, 46, 194)     # #1d2ec2  — primary
SPACE_CADET     = (31, 55, 89)      # #1f3759  — dark
WHITE           = (255, 255, 255)
LIGHT_GRAY      = (240, 240, 245)

# Logo CDN URL (blue version — for use on white backgrounds)
LOGO_URL        = "https://www.estropical.com/css/clientes/estropical/images/brand-primary.png"

# Fonts (downloaded to .tmp/fonts/ by install step or this script)
FONTS_DIR       = Path(".tmp/fonts")
FONT_BOLD_PATH  = FONTS_DIR / "Poppins-ExtraBold.ttf"
FONT_SEMI_PATH  = FONTS_DIR / "Poppins-SemiBold.ttf"

DELAY_SECONDS   = 0.3   # polite rate limit between image downloads

# ── Curated destination photos (Unsplash + Pexels — free commercial use) ──────
# Ordered list of (slug_keyword, url). First match wins — put more specific first.
# Unsplash: w=1200&q=90&fit=crop  |  Pexels: auto=compress&cs=tinysrgb&w=1200&h=1200
_BASE   = "https://images.unsplash.com"
_PEXELS = "https://images.pexels.com/photos"
DESTINATION_PHOTOS = [
    # ── Southeast Asia ────────────────────────────────────────────────────────
    ("vietnam",    f"{_PEXELS}/6348785/pexels-photo-6348785.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"),   # Ha Long Bay aerial ✓
    ("laos",       f"{_PEXELS}/6871179/pexels-photo-6871179.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"),   # Tropical waterfall ✓
    ("angkor",     f"{_PEXELS}/15928697/pexels-photo-15928697.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"), # Bayon Temple ✓
    ("camboya",    f"{_PEXELS}/15928697/pexels-photo-15928697.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"),
    ("cambodia",   f"{_PEXELS}/15928697/pexels-photo-15928697.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"),
    ("phi-phi",    f"{_BASE}/photo-1589394815804-964ed0be2eb5?w=1200&q=90&fit=crop"),  # Phi Phi turquoise bay
    ("phuket",     f"{_BASE}/photo-1537956965359-7573183d1f57?w=1200&q=90&fit=crop"),  # Phuket white-sand beach
    ("tailandia",  f"{_BASE}/photo-1506665531195-3566af2b4dfa?w=1200&q=90&fit=crop"),  # Bangkok Wat Arun
    ("thailand",   f"{_BASE}/photo-1506665531195-3566af2b4dfa?w=1200&q=90&fit=crop"),
    ("bali",       f"{_BASE}/photo-1555400038-63f5ba517a47?w=1200&q=90&fit=crop"),     # Tegalalang rice terraces
    # ── East Asia ─────────────────────────────────────────────────────────────
    ("nakasendo",  f"{_BASE}/photo-1493976040374-85c8e12f0c0e?w=1200&q=90&fit=crop"),  # Kyoto historic street
    ("japon",      f"{_BASE}/photo-1492571350019-22de08371fd3?w=1200&q=90&fit=crop"),  # Mount Fuji + lake
    ("japan",      f"{_BASE}/photo-1492571350019-22de08371fd3?w=1200&q=90&fit=crop"),
    ("corea",      f"{_BASE}/photo-1517154421773-0529f29ea451?w=1200&q=90&fit=crop"),  # Gyeongbokgung Palace
    ("korea",      f"{_BASE}/photo-1517154421773-0529f29ea451?w=1200&q=90&fit=crop"),
    ("avatar",     f"{_BASE}/photo-1536599018102-9f803c140fc1?w=1200&q=90&fit=crop"),  # Zhangjiajie pillars
    ("china",      f"{_BASE}/photo-1508804185872-d7badad00f7d?w=1200&q=90&fit=crop"),  # Great Wall at sunrise
    ("singapur",   f"{_BASE}/photo-1525625293386-3f8f99389edd?w=1200&q=90&fit=crop"),  # Marina Bay Sands
    ("singapore",  f"{_BASE}/photo-1525625293386-3f8f99389edd?w=1200&q=90&fit=crop"),
    ("borneo",     f"{_BASE}/photo-1549576490-b0b4831ef60a?w=1200&q=90&fit=crop"),     # Borneo rainforest
    ("kuala",      f"{_BASE}/photo-1596422846543-75c6fc197f07?w=1200&q=90&fit=crop"),  # Petronas Towers
    ("malasia",    f"{_BASE}/photo-1596422846543-75c6fc197f07?w=1200&q=90&fit=crop"),
    ("filipinas",  f"{_BASE}/photo-1518509562904-e7ef99cdcc86?w=1200&q=90&fit=crop"),  # El Nido lagoon
    ("philippines",f"{_BASE}/photo-1518509562904-e7ef99cdcc86?w=1200&q=90&fit=crop"),
    ("hong-kong",  f"{_BASE}/photo-1512453979798-5ea266f8880c?w=1200&q=90&fit=crop"),  # Victoria Harbour night
    # ── South Asia ────────────────────────────────────────────────────────────
    ("triangulo",  f"{_BASE}/photo-1524492412937-b28074a5d7da?w=1200&q=90&fit=crop"),  # Taj Mahal at dawn
    ("india",      f"{_BASE}/photo-1524492412937-b28074a5d7da?w=1200&q=90&fit=crop"),
    ("nepal",      f"{_BASE}/photo-1544735716-392fe2489ffa?w=1200&q=90&fit=crop"),     # Himalaya peaks
    # ── Africa — rocosas BEFORE victoria to avoid matching "Victoria, BC" ─────
    ("rocosas",    f"{_BASE}/photo-1503614472-8c93d56e92ce?w=1200&q=90&fit=crop"),     # Moraine Lake / Rockies
    ("cataratas",  f"{_BASE}/photo-1566837945700-30057527ade0?w=1200&q=90&fit=crop"),  # Victoria Falls
    ("victoria",   f"{_BASE}/photo-1566837945700-30057527ade0?w=1200&q=90&fit=crop"),
    ("zimbawe",    f"{_BASE}/photo-1566837945700-30057527ade0?w=1200&q=90&fit=crop"),
    ("zimbabwe",   f"{_BASE}/photo-1566837945700-30057527ade0?w=1200&q=90&fit=crop"),
    ("botswana",   f"{_BASE}/photo-1574068468668-a05a11f871da?w=1200&q=90&fit=crop"),  # Okavango elephants
    ("uganda",     f"{_BASE}/photo-1546182990-dffeafbe841d?w=1200&q=90&fit=crop"),     # Mountain gorillas
    ("tanzania",   f"{_BASE}/photo-1535941339077-2dd1c7963098?w=1200&q=90&fit=crop"),  # Serengeti
    ("kenya",      f"{_BASE}/photo-1547970810-dc1eac37d174?w=1200&q=90&fit=crop"),     # Maasai Mara lions
    ("kenia",      f"{_BASE}/photo-1547970810-dc1eac37d174?w=1200&q=90&fit=crop"),
    ("sudafrica",  f"{_BASE}/photo-1580060839134-75a5edca2e99?w=1200&q=90&fit=crop"),  # Cape Town/Table Mtn
    ("safari",     f"{_BASE}/photo-1547970810-dc1eac37d174?w=1200&q=90&fit=crop"),
    # ── Americas ──────────────────────────────────────────────────────────────
    ("buenos-aires",f"{_BASE}/photo-1523731407965-2430cd12f5e4?w=1200&q=90&fit=crop"), # La Boca
    ("nueva-york", f"{_BASE}/photo-1496442226666-8d4d0e62e6e9?w=1200&q=90&fit=crop"),  # Manhattan skyline
    ("new-york",   f"{_BASE}/photo-1496442226666-8d4d0e62e6e9?w=1200&q=90&fit=crop"),
    ("canada",     f"{_BASE}/photo-1503614472-8c93d56e92ce?w=1200&q=90&fit=crop"),     # Moraine Lake / Banff
    ("mexico",     f"{_BASE}/photo-1518105779142-d975f22f1b0a?w=1200&q=90&fit=crop"),  # Chichen Itza
    ("cuba",       f"{_BASE}/photo-1516466723877-e4ec1d736c8a?w=1200&q=90&fit=crop"),  # Havana vintage cars
    # ── Oceania ───────────────────────────────────────────────────────────────
    ("australia",  f"{_BASE}/photo-1523482580672-f109ba8cb9be?w=1200&q=90&fit=crop"),  # Sydney Opera House
    ("zelanda",    f"{_BASE}/photo-1507699622108-4be3abd695ad?w=1200&q=90&fit=crop"),  # Milford Sound fjord
    # ── Generic Asia fallbacks ────────────────────────────────────────────────
    ("indochina",  f"{_PEXELS}/6348785/pexels-photo-6348785.jpeg?auto=compress&cs=tinysrgb&w=1200&h=1200"),  # Ha Long Bay aerial ✓
    ("asiaticos",  f"{_BASE}/photo-1525625293386-3f8f99389edd?w=1200&q=90&fit=crop"),  # Singapore skyline
    ("oriente",    f"{_BASE}/photo-1506665531195-3566af2b4dfa?w=1200&q=90&fit=crop"),  # Bangkok
]

# Generic travel fallback (airplane above clouds)
FALLBACK_PHOTO = f"{_BASE}/photo-1436491865332-7a61a109cc05?w=1200&q=90&fit=crop"


def _photo_cache_key(url: str) -> str:
    """Extract photo ID from URL for use as a stable cache key (Unsplash or Pexels)."""
    # Unsplash: photo-XXXXXXXX-XXXXXXXX
    m = re.search(r'photo-[a-z0-9]+-[a-z0-9]+', url)
    if m:
        return m.group(0)
    # Pexels: /photos/12345/ or pexels-photo-12345
    m = re.search(r'/photos/(\d+)/', url)
    if m:
        return f"pexels-{m.group(1)}"
    return re.sub(r'[^\w]', '_', url)[:80]


def resolve_destination_photo(slug: str, title: str) -> str:
    """Return the best Unsplash photo URL by matching keywords in the slug."""
    text = (slug + " " + title).lower()
    for keyword, url in DESTINATION_PHOTOS:
        if keyword in text:
            return url
    return FALLBACK_PHOTO


# ── Destination label extraction ──────────────────────────────────────────────
# Patterns to remove from slug before converting to destination label
_SLUG_STRIP = re.compile(
    r'mm\d+[-]?|'
    r'lo[-_]mejor[-_]de[-_]|'
    r'complete[-_]|'
    r'colores[-_]de[-_]|'
    r'paquete[-_]a[-_]|'
    r'joyas[-_]de[-_]|'
    r'singapur[-_]|'          # keep others, remove just the prefix connector
    r'desde[-_].+$|'           # remove "desde-santa-cruz" suffixes
    r'[-_]\d{2,4}[-_\d]*$',   # remove year suffixes (-2026, -26-27)
    re.I
)

# Replace hyphens-between-words with space, title-case each word
def extract_destination(slug: str, title: str) -> str:
    """Return a short destination label (≤ 28 chars) from slug or title."""
    text = slug.lower()
    text = _SLUG_STRIP.sub(" ", text)
    text = text.replace("-", " ").replace("_", " ").strip()
    # Title-case, keep Spanish connectors lowercase
    KEEP_LOWER = {"y", "e", "o", "de", "del", "con", "y"}
    words = text.split()
    result = []
    for i, w in enumerate(words):
        if i > 0 and w in KEEP_LOWER:
            result.append(w)
        else:
            result.append(w.capitalize())
    dest = " ".join(result).strip()

    # Fallback to cleaned title keywords if slug gave nothing useful
    if len(dest) < 3:
        # Extract first meaningful noun phrase from title
        dest = re.sub(r'^(?:lo mejor de|colores de|complete|joyas de)\s+', '', title, flags=re.I)
        dest = re.sub(r'\s+\d{4}.*$', '', dest).strip()

    return dest[:28]


# ── Font loader ───────────────────────────────────────────────────────────────
def _ensure_fonts():
    """Download Poppins fonts if not already present."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    fonts = {
        FONT_BOLD_PATH: "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-ExtraBold.ttf",
        FONT_SEMI_PATH: "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf",
    }
    for path, url in fonts.items():
        if not path.exists():
            print(f"  Downloading font: {path.name} ...")
            urllib.request.urlretrieve(url, path)


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


# ── Logo loader ───────────────────────────────────────────────────────────────
_logo_cache: Optional[Image.Image] = None

def get_logo() -> Image.Image:
    global _logo_cache
    if _logo_cache is not None:
        return _logo_cache
    logo_local = CACHE_DIR / "brand-primary.png"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not logo_local.exists():
        urllib.request.urlretrieve(LOGO_URL, logo_local)
    _logo_cache = Image.open(logo_local).convert("RGBA")
    return _logo_cache


# ── Image downloader ──────────────────────────────────────────────────────────
def download_image(url: str, cache_key: str) -> Optional[Image.Image]:
    """Download or load from cache a product source image."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitize cache filename
    safe_key = re.sub(r'[^\w.-]', '_', cache_key)[:80]
    cache_path = CACHE_DIR / f"{safe_key}.jpg"
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            cache_path.unlink(missing_ok=True)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FeedBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.save(cache_path, "JPEG", quality=90)
        return img
    except Exception as e:
        print(f"    ⚠ Could not download image ({e})")
        return None


# ── Smart crop / fill ─────────────────────────────────────────────────────────
def fill_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale image to cover target dimensions, then center-crop."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


# ── Gradient overlay ──────────────────────────────────────────────────────────
def make_gradient_overlay(w: int, h: int, alpha_top: int = 0, alpha_bot: int = 140) -> Image.Image:
    """Return an RGBA gradient image (transparent → dark from top to bottom)."""
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for y in range(h):
        alpha = int(alpha_top + (alpha_bot - alpha_top) * (y / h))
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    return grad


# ── Branded image composer ────────────────────────────────────────────────────
def compose_branded_image(
    source_img: Image.Image,
    destination_label: str,
    font_bold: ImageFont.FreeTypeFont,
    font_semi: ImageFont.FreeTypeFont,
) -> Image.Image:
    """
    Compose a 1080×1080 branded product image (square — Instagram/Meta/TikTok):
      ┌─────────────────────────────────────┐
      │  Destination photo (1080 × 950)     │
      │  with subtle bottom gradient        │
      ├─────────────────────────────────────┤
      │ [estropical logo]  DESTINATION NAME │  ← white strip, 130 px
      └─────────────────────────────────────┘
    """
    # ── 1. Photo section ──────────────────────────────────────────────────────
    photo = fill_crop(source_img, IMG_W, PHOTO_H)

    # Subtle dark gradient at the very bottom of the photo (helps visual transition)
    grad = make_gradient_overlay(IMG_W, PHOTO_H, alpha_top=0, alpha_bot=80)
    photo_rgba = photo.convert("RGBA")
    photo_rgba = Image.alpha_composite(photo_rgba, grad)

    # ── 2. Assemble full canvas ───────────────────────────────────────────────
    canvas = Image.new("RGBA", (IMG_W, IMG_H), WHITE + (255,))
    canvas.paste(photo_rgba, (0, 0))

    # ── 3. White brand strip ──────────────────────────────────────────────────
    strip_y = PHOTO_H
    strip = Image.new("RGBA", (IMG_W, STRIP_H), WHITE + (255,))

    # Top accent line: thin Persian Blue rule
    draw_strip = ImageDraw.Draw(strip)
    draw_strip.rectangle([(0, 0), (IMG_W, 3)], fill=PERSIAN_BLUE + (255,))

    canvas.paste(strip, (0, strip_y))

    # ── 4. Estropical logo in strip ───────────────────────────────────────────
    logo = get_logo()
    logo_orig_w, logo_orig_h = logo.size

    # Scale logo to fit within left portion of strip
    max_logo_w = 280
    max_logo_h = STRIP_H - 30   # 15px padding top + bottom
    scale = min(max_logo_w / logo_orig_w, max_logo_h / logo_orig_h)
    logo_w = int(logo_orig_w * scale)
    logo_h = int(logo_orig_h * scale)
    logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)

    logo_x = 28
    logo_y = strip_y + (STRIP_H - logo_h) // 2
    canvas.paste(logo_resized, (logo_x, logo_y), logo_resized)

    # ── 5. Destination label in strip ─────────────────────────────────────────
    draw = ImageDraw.Draw(canvas)

    # Measure text width to right-align with margin
    MARGIN_RIGHT = 28
    dest_upper = destination_label.upper()

    # Try fitting at size 36, reduce if too wide
    for font_size in [38, 34, 30, 26]:
        try:
            fnt = ImageFont.truetype(str(FONT_BOLD_PATH), font_size)
        except Exception:
            fnt = font_bold
        bbox = draw.textbbox((0, 0), dest_upper, font=fnt)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= IMG_W - logo_x - logo_w - 60:
            break

    text_x = IMG_W - text_w - MARGIN_RIGHT
    text_y = strip_y + (STRIP_H - text_h) // 2 - 2

    draw.text((text_x, text_y), dest_upper, font=fnt, fill=PERSIAN_BLUE)

    # ── 6. Thin separator line between logo and text (optional visual anchor) ─
    sep_x = logo_x + logo_w + 18
    sep_y1 = strip_y + 18
    sep_y2 = strip_y + STRIP_H - 18
    draw.rectangle([(sep_x, sep_y1), (sep_x + 2, sep_y2)], fill=LIGHT_GRAY)

    return canvas.convert("RGB")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not INPUT_PATH.exists():
        print(f"❌ {INPUT_PATH} not found. Run python tools/scrape_catalog.py first.")
        raise SystemExit(1)

    _ensure_fonts()

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    products = data["products"]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    font_bold = load_font(FONT_BOLD_PATH, 38)
    font_semi = load_font(FONT_SEMI_PATH, 22)

    manifest = {}
    skipped  = 0
    generated = 0

    print(f"Generating branded images for {len(products)} products...\n")

    for product in products:
        pid       = product["id"]
        src_url   = product.get("image_link", "")
        slug      = product.get("slug", "")
        title     = product.get("title", "")
        out_path  = OUTPUT_DIR / f"{pid}.jpg"

        dest_label = extract_destination(slug, title)
        public_url = f"{GITHUB_PAGES_BASE}/{pid}.jpg?v=2"

        manifest[pid] = public_url

        # Skip if already generated (won't re-download unless forced)
        if out_path.exists():
            print(f"  [skip] {pid} — already exists")
            skipped += 1
            continue

        print(f"  [{generated+1+skipped}/{len(products)}] {pid} — {dest_label}")

        # Resolve destination photo: curated Unsplash → scraped og:image → placeholder
        photo_url  = resolve_destination_photo(slug, title)
        cache_key  = _photo_cache_key(photo_url)
        source_img = download_image(photo_url, cache_key)
        if source_img is None and src_url and src_url.startswith("http"):
            # Fallback to scraped TravelConLine image
            print(f"    ⚠ Unsplash failed — trying scraped image")
            source_img = download_image(src_url, pid)
        if source_img is None:
            source_img = Image.new("RGB", (1200, 628), (29, 46, 194))
        time.sleep(DELAY_SECONDS)

        # Compose branded image
        branded = compose_branded_image(source_img, dest_label, font_bold, font_semi)
        branded.save(out_path, "JPEG", quality=88, optimize=True)
        generated += 1

    # Save manifest
    MANIFEST_PATH.parent.mkdir(exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✅ Done — {generated} images generated, {skipped} skipped (already existed)")
    print(f"   Output : {OUTPUT_DIR}/")
    print(f"   Manifest: {MANIFEST_PATH}")
    print(f"\n📡 Images will be served from:")
    print(f"   {GITHUB_PAGES_BASE}/{{product_id}}.jpg")
    print(f"\n💡 Force-regen all: delete docs/images/ and re-run")


if __name__ == "__main__":
    main()
