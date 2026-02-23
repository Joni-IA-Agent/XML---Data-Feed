"""
scrape_catalog.py — Estropical.com Product Catalog Scraper
===========================================================
Paginates through https://www.estropical.com/en/moreideas (PrimeFaces AJAX)
to collect idea URLs, then scrapes each individual idea page for:
  - id         : TravelConLine numeric idea ID  → g:id in the XML feed
  - link        : canonical idea URL            → g:link
  - image_link  : og:image from the page        → g:image_link
  - title, description, price, region, type

Run:    python tools/scrape_catalog.py
Output: .tmp/products_raw.json
"""

import datetime
import json
import re
import time
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL        = "https://www.estropical.com"
MOREIDEAS_URL   = f"{BASE_URL}/en/moreideas"
OUTPUT_PATH     = Path(".tmp/products_raw.json")
DELAY_SECONDS   = 1.0       # polite delay between idea-page requests
PAGE_DELAY      = 0.5       # delay between AJAX pagination calls
MAX_RETRIES     = 3
REQUEST_TIMEOUT = 15
MAX_IDEAS       = 500       # cap for daily scrape (4390 available; 500 ≈ 10 min)
ROWS_PER_PAGE   = 12        # matches PrimeFaces DataView config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With":   "XMLHttpRequest",
    "Content-Type":       "application/x-www-form-urlencoded; charset=UTF-8",
    "Faces-Request":      "partial/ajax",
    "Accept":             "application/xml, text/xml, */*; q=0.01",
    "Referer":            MOREIDEAS_URL,
    "Origin":             BASE_URL,
}

# ── Region inference ──────────────────────────────────────────────────────────
REGION_KEYWORDS: List[tuple] = [
    ("cancun", "Caribe"), ("cancún", "Caribe"),
    ("punta-cana", "Caribe"), ("punta cana", "Caribe"), ("caribe", "Caribe"),
    ("miami", "Norteamérica"), ("nueva-york", "Norteamérica"),
    ("nueva york", "Norteamérica"), ("new york", "Norteamérica"),
    ("orlando", "Norteamérica"), ("washington", "Norteamérica"),
    ("estados-unidos", "Norteamérica"), ("estados unidos", "Norteamérica"),
    ("madrid", "Europa"), ("barcelona", "Europa"),
    ("paris", "Europa"), ("europa", "Europa"),
    ("buenos-aires", "Sudamérica"), ("buenos aires", "Sudamérica"),
    ("sao-paulo", "Sudamérica"), ("são paulo", "Sudamérica"),
    ("rio-de-janeiro", "Sudamérica"), ("santiago", "Sudamérica"),
    ("lima", "Sudamérica"), ("bogota", "Sudamérica"), ("bogotá", "Sudamérica"),
    ("cartagena", "Sudamérica"), ("asuncion", "Sudamérica"), ("asunción", "Sudamérica"),
    ("tailandia", "Asia"), ("bangkok", "Asia"), ("vietnam", "Asia"),
    ("laos", "Asia"), ("japon", "Asia"), ("japón", "Asia"),
    ("tokio", "Asia"), ("tokyo", "Asia"), ("dubai", "Asia"), ("corea", "Asia"),
    ("panama", "Centroamérica"), ("méxico", "Centroamérica"), ("mexico", "Centroamérica"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_with_retry(
    session: requests.Session,
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    extra_headers: Optional[dict] = None,
    retries: int = MAX_RETRIES,
) -> Optional[requests.Response]:
    headers = extra_headers or {}
    for attempt in range(retries):
        try:
            if method == "POST":
                resp = session.post(url, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
            else:
                resp = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            print(f"  [{resp.status_code}] {url}")
            return None
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  Error {url}: {e}. Retry in {wait}s...")
            time.sleep(wait)
    return None


def extract_idea_id(url: str) -> Optional[str]:
    m = re.search(r"/idea/(\d+)/", url)
    return m.group(1) if m else None


def parse_price(text: str) -> Optional[float]:
    m = re.search(r"[\$US]+\s*([0-9][0-9,\.]+)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def infer_region(text: str) -> str:
    lower = text.lower()
    for keyword, region in REGION_KEYWORDS:
        if keyword in lower:
            return region
    return "Internacional"


def infer_product_type(slug: str, title: str) -> str:
    combined = (slug + " " + title).lower()
    if re.search(r"\bboleto\b|\bvuelo\b|\bticket\b|\bflight\b|\bairfare\b", combined):
        return "Vuelo"
    if re.search(r"\bhotel\b|\bresort\b|\binn\b|\blodge\b|\bpalace\b|\bsuites\b|\bapartment\b", combined):
        return "Hotel"
    return "Paquete"


# ── Discovery: paginate moreideas via PrimeFaces AJAX ─────────────────────────
def discover_idea_urls(session: requests.Session, max_ideas: int) -> List[str]:
    """
    Paginates through /en/moreideas using PrimeFaces DataView AJAX calls
    and returns a deduplicated list of up to max_ideas full idea URLs.
    """
    print(f"Loading {MOREIDEAS_URL} ...")
    resp = fetch_with_retry(session, MOREIDEAS_URL)
    if not resp:
        raise RuntimeError("Cannot load moreideas page")

    soup = BeautifulSoup(resp.text, "lxml")
    vs_input = soup.find("input", {"name": "javax.faces.ViewState"})
    if not vs_input:
        raise RuntimeError("ViewState not found on moreideas page")
    viewstate = vs_input["value"]

    # Extract idea links from the initial HTML
    seen_ids: set = set()
    idea_urls: List[str] = []

    def collect_links(html: str) -> None:
        # Matches both absolute and relative idea URLs in href attributes
        for href in re.findall(
            r'href="((?:https://www\.estropical\.com)?/(?:en|es)/idea/\d+/[^"]*)"',
            html
        ):
            idea_id = extract_idea_id(href)
            if idea_id and idea_id not in seen_ids:
                seen_ids.add(idea_id)
                full = href if href.startswith("http") else BASE_URL + href
                idea_urls.append(full)

    collect_links(resp.text)
    print(f"  Page 1: {len(idea_urls)} ideas found so far")

    # Paginate via AJAX
    first = ROWS_PER_PAGE  # start from page 2
    while len(idea_urls) < max_ideas:
        time.sleep(PAGE_DELAY)
        post_data = {
            "form:selectSecondaryCategory": "",
            "form:inputTextSearchIdea":     "",
            "form:addDestination_input":    "",
            "form:addDestination_hinput":   "",
            "form_SUBMIT":                  "1",
            "javax.faces.partial.ajax":     "true",
            "javax.faces.source":           "form:ideasDataView",
            "javax.faces.partial.execute":  "@all",
            "javax.faces.partial.render":   "form:ideasDataView",
            "javax.faces.behavior.event":   "page",
            "javax.faces.partial.event":    "page",
            "form:ideasDataView_pagination":"true",
            "form:ideasDataView_first":     str(first),
            "form:ideasDataView_rows":      str(ROWS_PER_PAGE),
            "form":                         "form",
            "javax.faces.ViewState":        viewstate,
        }

        page_resp = fetch_with_retry(
            session, MOREIDEAS_URL, method="POST",
            data=post_data, extra_headers=AJAX_HEADERS
        )
        if not page_resp:
            print(f"  Page offset {first}: request failed — stopping")
            break

        # Update ViewState from AJAX response (it rotates)
        new_vs = re.search(
            r'id="j_id__v_0:javax\.faces\.ViewState:\d+"><!\[CDATA\[([^\]]+)\]\]>',
            page_resp.text
        )
        if new_vs:
            viewstate = new_vs.group(1)

        before = len(idea_urls)
        collect_links(page_resp.text)
        added = len(idea_urls) - before

        # Stop if no new ideas were found (exhausted or filter returned empty)
        if added == 0:
            print(f"  No new ideas at offset {first} — stopping")
            break

        page_num = first // ROWS_PER_PAGE + 1
        print(f"  Page {page_num} (offset={first}): +{added} ideas, total={len(idea_urls)}")

        first += ROWS_PER_PAGE

    return idea_urls[:max_ideas]


# ── Scraping individual idea pages ────────────────────────────────────────────
def scrape_idea_page(session: requests.Session, url: str) -> Optional[dict]:
    """Fetch an idea page and extract title, description, og:image, price."""
    resp = fetch_with_retry(session, url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    def og(prop: str) -> str:
        tag = soup.find("meta", property=f"og:{prop}") or soup.find("meta", attrs={"name": prop})
        return tag["content"].strip() if tag and tag.get("content") else ""

    title       = og("title") or (soup.title.text.strip() if soup.title else "")
    description = og("description")
    image_link  = og("image")

    price: Optional[float] = None
    for pt in soup.find_all(string=re.compile(r"[Dd]esde\s*US\$|[Dd]esde\s*\$|[Ff]rom\s*US\$")):
        p = parse_price(pt)
        if p and p > 50:
            price = p
            break

    slug   = url.rstrip("/").split("/")[-1]
    region = infer_region(slug + " " + title)
    ptype  = infer_product_type(slug, title)

    return {
        "title":       title[:150],
        "description": description[:1000] if description else title,
        "image_link":  image_link,
        "price":       price,
        "link":        url,
        "region":      region,
        "slug":        slug,
        "type":        ptype,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    session = make_session()

    # 1. Discover idea URLs from moreideas page (paginated)
    idea_urls = discover_idea_urls(session, MAX_IDEAS)
    print(f"\nDiscovered {len(idea_urls)} idea URLs. Starting scrape...\n")

    # 2. Scrape each individual idea page for real data + og:image
    products: List[dict] = []
    for i, url in enumerate(idea_urls, 1):
        idea_id = extract_idea_id(url)
        if not idea_id:
            continue

        print(f"[{i}/{len(idea_urls)}] {idea_id} — {url.split('/')[-1][:50]}")
        data = scrape_idea_page(session, url)
        time.sleep(DELAY_SECONDS)

        if not data:
            print("  ⚠ Skipped (no data)")
            continue

        products.append({
            "id":          idea_id,
            "type":        data["type"],
            "title":       data["title"],
            "description": data["description"],
            "link":        data["link"],         # real idea URL → g:link
            "image_link":  data["image_link"],   # og:image      → g:image_link
            "price":       data["price"],
            "region":      data["region"],
            "slug":        data["slug"],
        })

    # 3. Save
    summary = {
        "scraped_at": datetime.datetime.utcnow().isoformat() + "Z",
        "count":      len(products),
        "products":   products,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    vuelos   = sum(1 for p in products if p["type"] == "Vuelo")
    hoteles  = sum(1 for p in products if p["type"] == "Hotel")
    paquetes = sum(1 for p in products if p["type"] == "Paquete")

    print(f"\n✅ Done — {len(products)} ideas saved to {OUTPUT_PATH}")
    print(f"   Vuelos  : {vuelos}")
    print(f"   Hoteles : {hoteles}")
    print(f"   Paquetes: {paquetes}")


if __name__ == "__main__":
    main()
