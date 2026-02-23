"""
generate_xml_feed.py — Estropical.com XML Product Feed Generator
=================================================================
Reads .tmp/products_raw.json (produced by scrape_catalog.py) and
generates docs/estropical_catalog.xml — a Google Base / RSS 2.0 feed
compatible with:
  ✅ Google Merchant Center
  ✅ Meta Ads (Facebook / Instagram Catalog)
  ✅ TikTok Ads

Dynamic Remarketing ID Scheme:
  All products → {TRAVELCONLINE_NUMERIC_IDEA_ID}  e.g. 46865178
  GTM (GTM-MR5PGKT) must fire this ID as content_ids / item_id
  when users visit the corresponding /idea/{ID}/ page.

Run:    python tools/generate_xml_feed.py
Output: docs/estropical_catalog.xml
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

# ── Paths ─────────────────────────────────────────────────────────────────────
INPUT_PATH  = Path(".tmp/products_raw.json")
OUTPUT_PATH = Path("docs/estropical_catalog.xml")

# ── Fallback destination images (Unsplash — free commercial use) ──────────────
# Used only when og:image is absent or a placeholder.
DESTINATION_IMAGES: dict = {
    # Caribe y México
    "CUN": "https://images.unsplash.com/photo-1552074284-5e88ef1aef18?w=800&q=80",
    "PUJ": "https://images.unsplash.com/photo-1580500659429-7df0f7a34c8b?w=800&q=80",
    "MEX": "https://images.unsplash.com/photo-1518105779142-d975f22f1b0a?w=800&q=80",
    # Centroamérica
    "PTY": "https://images.unsplash.com/photo-1575115022853-cb5db71e7d20?w=800&q=80",
    # Norteamérica
    "MIA": "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800&q=80",
    "MCO": "https://images.unsplash.com/photo-1575550959106-5a7defe28b56?w=800&q=80",
    "JFK": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=800&q=80",
    "IAD": "https://images.unsplash.com/photo-1501466044931-62695aada8e9?w=800&q=80",
    # Sudamérica
    "ASU": "https://images.unsplash.com/photo-1598928636135-d146006ff4be?w=800&q=80",
    "EZE": "https://images.unsplash.com/photo-1518391846015-55a9cc003b25?w=800&q=80",
    "GRU": "https://images.unsplash.com/photo-1541388354-baa5a37b90a2?w=800&q=80",
    "GIG": "https://images.unsplash.com/photo-1483729558449-99ef09a8c325?w=800&q=80",
    "SCL": "https://images.unsplash.com/photo-1555441580-3e2ee3c5ddf4?w=800&q=80",
    "LIM": "https://images.unsplash.com/photo-1526392060635-9d6019884377?w=800&q=80",
    "BOG": "https://images.unsplash.com/photo-1588614959060-4d144f28b207?w=800&q=80",
    "CTG": "https://images.unsplash.com/photo-1576487236230-eaa4afe68192?w=800&q=80",
    # Europa
    "MAD": "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?w=800&q=80",
    "BCN": "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?w=800&q=80",
    "CDG": "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=800&q=80",
    # Asia
    "BKK": "https://images.unsplash.com/photo-1506665531195-3566af2b4dfa?w=800&q=80",
    "TYO": "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=800&q=80",
    # Fallback
    "DEFAULT": "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?w=800&q=80",
}

KEYWORD_TO_IATA: dict = {
    "cancun": "CUN", "cancún": "CUN",
    "punta-cana": "PUJ", "punta cana": "PUJ",
    "miami": "MIA",
    "orlando": "MCO",
    "nueva-york": "JFK", "nueva york": "JFK", "new york": "JFK",
    "washington": "IAD",
    "madrid": "MAD",
    "barcelona": "BCN",
    "paris": "CDG", "parís": "CDG",
    "buenos-aires": "EZE", "buenos aires": "EZE",
    "sao-paulo": "GRU", "são paulo": "GRU",
    "rio-de-janeiro": "GIG", "río de janeiro": "GIG",
    "santiago": "SCL",
    "lima": "LIM",
    "bogota": "BOG", "bogotá": "BOG",
    "cartagena": "CTG",
    "ciudad-de-panama": "PTY", "panama": "PTY",
    "tailandia": "BKK", "bangkok": "BKK",
    "vietnam": "BKK",
    "japon": "TYO", "japón": "TYO", "tokio": "TYO", "tokyo": "TYO",
    "mexico": "MEX", "ciudad-de-mexico": "MEX",
    "asuncion": "ASU", "asunción": "ASU",
}


def resolve_image(product: dict) -> str:
    """
    Return the best image URL for a product.
    Priority:
      1. og:image scraped from the idea page (if it's a real photo, not a placeholder)
      2. Unsplash fallback matched by destination keyword in slug/title
      3. Generic travel fallback
    """
    scraped = (product.get("image_link") or "").strip()

    # Accept any real image URL — reject empty strings and the placeholder filename
    if scraped and "no-photo" not in scraped and scraped.startswith("http"):
        return scraped

    # Fallback: keyword match → Unsplash destination photo
    text = (
        product.get("slug", "") + " "
        + product.get("title", "") + " "
        + product.get("region", "")
    ).lower()
    for keyword, code in KEYWORD_TO_IATA.items():
        if keyword in text:
            return DESTINATION_IMAGES.get(code, DESTINATION_IMAGES["DEFAULT"])

    return DESTINATION_IMAGES["DEFAULT"]


def price_range_label(price: Optional[float]) -> str:
    if price is None:
        return "Consultar"
    if price < 500:
        return "Hasta $500"
    elif price < 1000:
        return "$500-$1000"
    elif price < 3000:
        return "$1000-$3000"
    else:
        return "+$3000"


def infer_season(title: str, slug: str) -> str:
    combined = (title + " " + slug).lower()
    if "semana santa" in combined or "semana-santa" in combined:
        return "Semana Santa"
    if "2026" in combined:
        return "2026"
    if "navidad" in combined or "fin-de-año" in combined or "fin-de-ano" in combined:
        return "Navidad / Fin de Año"
    return "Todo el año"


# ── XML helpers ───────────────────────────────────────────────────────────────
def x(tag: str, value: Optional[str], ns: bool = True) -> str:
    """Return a single XML tag line. Skips empty / blank values."""
    if value is None or str(value).strip() == "":
        return ""
    prefix = "g:" if ns else ""
    return f"      <{prefix}{tag}>{escape(str(value))}</{prefix}{tag}>\n"


def build_item(
    product_id: str,
    title: str,
    description: str,
    link: str,
    image_link: str,
    price: float,
    product_type: str,
    brand: str = "Estropical",
    item_group_id: Optional[str] = None,
    cl0: str = "",   # custom_label_0 → product type
    cl1: str = "",   # custom_label_1 → region
    cl2: str = "",   # custom_label_2 → price range
    cl3: str = "",   # custom_label_3 → idea ID (for GTM)
    cl4: str = "",   # custom_label_4 → season/promo
) -> str:
    price_str = f"{price:.2f} USD"
    lines  = "    <item>\n"
    lines += x("id",           product_id)
    lines += x("title",        title[:150])
    lines += x("description",  description[:4990])
    lines += x("link",         link)
    lines += x("image_link",   image_link)
    lines += x("price",        price_str)
    lines += x("availability", "in stock")
    lines += x("condition",    "new")
    lines += x("brand",        brand)
    lines += x("product_type", product_type)
    if item_group_id:
        lines += x("item_group_id", item_group_id)
    if cl0: lines += x("custom_label_0", cl0)
    if cl1: lines += x("custom_label_1", cl1)
    if cl2: lines += x("custom_label_2", cl2)
    if cl3: lines += x("custom_label_3", cl3)
    if cl4: lines += x("custom_label_4", cl4)
    lines += "    </item>\n\n"
    return lines


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not INPUT_PATH.exists():
        print(f"❌ Input file not found: {INPUT_PATH}")
        print("   Run: python tools/scrape_catalog.py first.")
        raise SystemExit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    products     = data["products"]          # flat list of idea dicts
    scraped_at   = data.get("scraped_at", "")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    OUTPUT_PATH.parent.mkdir(exist_ok=True)

    # ── Build XML ─────────────────────────────────────────────────────────────
    parts: list = []

    parts.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    parts.append(f'''<!--
  ================================================================
  CATÁLOGO DE PRODUCTOS — ESTROPICAL.COM
  ================================================================
  Generado : {generated_at}
  Fuente   : {INPUT_PATH} (scraped {scraped_at})

  COMPATIBILIDAD:
    ✅ Google Merchant Center  — RSS 2.0 + Google Base namespace
    ✅ Meta Ads                — RSS 2.0 catalog feed
    ✅ TikTok Ads              — Google Shopping XML

  ESQUEMA DE IDs (para Dynamic Remarketing via GTM-MR5PGKT):
    Todos los productos → {{IDEA_NUMERIC_ID}}  ej: 46865178
    GTM debe disparar ese ID como content_ids / item_id
    cuando el usuario visita /idea/{{ID}}/ en el sitio.

  Total: {len(products)} ideas
  ================================================================
-->\n''')

    parts.append('<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n')
    parts.append('  <channel>\n')
    parts.append('    <title>Estropical — Vuelos, Hoteles y Paquetes</title>\n')
    parts.append('    <link>https://www.estropical.com</link>\n')
    parts.append(
        '    <description>Catálogo oficial de vuelos, hoteles y paquetes turísticos '
        'de Estropical, agencia de viajes líder en Bolivia.</description>\n\n'
    )

    counters = {"Vuelo": 0, "Hotel": 0, "Paquete": 0}

    for product in products:
        image  = resolve_image(product)
        price  = product.get("price") or 299.00
        ptype  = product.get("type", "Paquete")
        region = product.get("region", "Internacional")
        season = infer_season(product.get("title", ""), product.get("slug", ""))

        # product_type path for Google taxonomy
        type_path = {
            "Vuelo":   f"Viajes > Vuelos > {region}",
            "Hotel":   f"Viajes > Hoteles > {region}",
            "Paquete": f"Viajes > Paquetes > {region}",
        }.get(ptype, f"Viajes > {ptype} > {region}")

        # item_group_id groups same product-type by region
        safe_region = (
            region.upper()
            .replace(" ", "-")
            .replace("É", "E").replace("Á", "A")
            .replace("Ú", "U").replace("Ó", "O")
            .replace("Í", "I")
        )
        item_group = f"{ptype.upper()}-{safe_region}"

        counters[ptype] = counters.get(ptype, 0) + 1

        parts.append(
            build_item(
                product_id   = product["id"],
                title        = product["title"],
                description  = product.get("description") or product["title"],
                link         = product["link"],
                image_link   = image,
                price        = price,
                product_type = type_path,
                item_group_id= item_group,
                cl0          = ptype,
                cl1          = region,
                cl2          = price_range_label(price),
                cl3          = product["id"],   # idea ID → GTM reads this for remarketing
                cl4          = season,
            )
        )

    parts.append('  </channel>\n')
    parts.append('</rss>\n')

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.writelines(parts)

    print(f"✅ Feed generated: {OUTPUT_PATH}")
    print(f"   Vuelos  : {counters.get('Vuelo', 0)}")
    print(f"   Hoteles : {counters.get('Hotel', 0)}")
    print(f"   Paquetes: {counters.get('Paquete', 0)}")
    print(f"   Total   : {len(products)} productos")
    print(f"\n📡 Public URL (after GitHub Pages setup):")
    print(f"   https://[your-github-username].github.io/XML---Data-Feed/estropical_catalog.xml")


if __name__ == "__main__":
    main()
