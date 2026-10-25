"""Parse a page you saved yourself from your normal browser (Ctrl+S -> "Webpage, Complete" or HTML only).

Use this for sites that block automated browsers. No requests are made to the site.

Usage:
    python parse_saved.py g2 path/to/saved_g2.html
    python parse_saved.py zillow path/to/saved_zillow.html
    python parse_saved.py stockx path/to/saved_stockx.html

Writes output/<site>.json with "source": "saved_page" so it is clear how the data was obtained.
"""
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

OUT = Path(__file__).parent / "output"
G2_RATING = re.compile(r"^(\d(?:\.\d)?)\s*/\s*5$")


def parse_g2(soup):
    out, seen = [], set()
    for el in soup.find_all(string=G2_RATING):
        node = el.parent
        link = None
        for _ in range(10):  # climb to the card that holds the product link
            if node is None:
                break
            for a in node.select('a[href*="/products/"]'):
                t = a.get_text(" ", strip=True)
                if len(t) > 2 and not re.search(r"try for free|reviews?$", t, re.I):
                    link = a
                    break
            if link:
                break
            node = node.parent
        if not link:
            continue
        name = link.get_text(" ", strip=True)
        if name in seen:
            continue
        seen.add(name)
        out.append({"product_name": name,
                    "star_rating": G2_RATING.match(el.strip()).group(1)})
    return out


ZILLOW_EMBEDDED = re.compile(
    r'"detailUrl":"([^"]+)","statusType":"([^"]*)","statusText":"[^"]*",'
    r'"countryCurrency":"[^"]*","price":"([^"]+)","unformattedPrice":\d+,"address":"([^"]+)"')


def parse_zillow(soup):
    out = []
    # 1) Search pages embed every loaded listing in the page state: clean price + full address.
    seen = set()
    for url, status, price, address in ZILLOW_EMBEDDED.findall(str(soup)):
        if url in seen:
            continue
        seen.add(url)
        out.append({"price": price, "address": address, "status": status, "url": url})
    if out:
        return out
    # Listing/detail pages publish schema.org JSON-LD with an Offer (price) and a PostalAddress.
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            d = json.loads(tag.get_text())
        except ValueError:
            continue
        for item in (d if isinstance(d, list) else [d]):
            offer = item.get("offers") if isinstance(item, dict) else None
            if not isinstance(offer, dict) or offer.get("price") is None:
                continue
            a = (offer.get("itemOffered") or {}).get("address") or {}
            address = ", ".join(str(x) for x in (
                a.get("streetAddress"), a.get("addressLocality"),
                f"{a.get('addressRegion', '')} {a.get('postalCode', '')}".strip()) if x)
            out.append({"price": f"${int(float(offer['price'])):,}",
                        "address": address or item.get("name"),
                        "url": item.get("url")})
    if out:
        return out
    for card in soup.select("article[data-test='property-card'], li article"):  # search-results page
        price = card.select_one("[data-test='property-card-price']")
        addr = card.select_one("address, [data-test='property-card-addr']")
        if price or addr:
            out.append({"price": price.get_text(strip=True) if price else None,
                        "address": addr.get_text(strip=True) if addr else None})
    return out


def parse_stockx(soup):
    for tag in soup.select("script[type='application/ld+json']"):
        m = re.search(r'"(?:lowPrice|price)"\s*:\s*"?(\d+(?:\.\d+)?)', tag.get_text())
        if m:
            return {"product": soup.title.get_text(strip=True) if soup.title else None,
                    "current_market_price": "$" + m.group(1)}
    return None


PARSERS = {"g2": parse_g2, "zillow": parse_zillow, "stockx": parse_stockx}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in PARSERS:
        sys.exit(__doc__)
    site, path = sys.argv[1], Path(sys.argv[2])
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    data = PARSERS[site](soup)
    record = {"site": site, "status": "ok" if data else "empty", "source": "saved_page",
              "data": data or None}
    if not data:
        record["note"] = "no records found in the saved page (wrong page saved, or markup changed)"
    OUT.mkdir(exist_ok=True)
    (OUT / f"{site}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    n = len(data) if isinstance(data, list) else int(bool(data))
    print(f"{site}: {record['status']} ({n} records) -> output/{site}.json")


if __name__ == "__main__":
    main()
