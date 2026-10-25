"""Dedicated Real-Time StockX Price Scraper

Features:
- Playwright-driven persistent Chrome session with anti-detection flags
- Handles Cloudflare Turnstile & DataDome perimeter challenges
- Multi-tier price extraction:
    1. Schema.org AggregateOffer (lowPrice, highPrice, size-level offers)
    2. Live DOM grounding (Last Sale, Lowest Ask, Highest Bid/Sell Now)
    3. Network GraphQL response interception fallback
- Exports structured JSON to output/stockx.json

Usage:
    python stockx_scraper.py
    python stockx_scraper.py https://stockx.com/nike-air-force-1-low-supreme-box-logo-white
    python stockx_scraper.py --headless
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROFILE_DIR = BASE_DIR / ".profile"
DEFAULT_URL = "https://stockx.com/nike-air-force-1-low-supreme-box-logo-white"

CHALLENGE_KEYWORDS = (
    "just a moment",
    "verify you are human",
    "captcha",
    "access denied",
    "security check",
    "blocked",
)


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def is_challenge_active(page) -> bool:
    try:
        title = page.title() or ""
        body_text = page.inner_text("body", timeout=1000)[:500] if page.locator("body").count() else ""
        combined = f"{title} {body_text}".lower()
        return any(w in combined for w in CHALLENGE_KEYWORDS)
    except Exception:
        return False


def scrape_stockx(url: str = DEFAULT_URL, headless: bool = False, max_wait: int = 45) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "stockx.json"
    
    log(f"Starting StockX scraper for target: {url}")
    log(f"Browser mode: {'headless' if headless else 'headed (visible Chrome with persistent profile)'}")

    result = {
        "status": "failed",
        "url": url,
        "product_name": None,
        "current_market_price": None,
        "last_sale_price": None,
        "highest_bid_price": None,
        "price_range": None,
        "sku": None,
        "size_offers": [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    with sync_playwright() as p:
        log("Launching Chrome persistent context with anti-automation flags...")
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            viewport={"width": 1366, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
            locale="en-US"
        )
        page = context.new_page()

        # Intercept background GraphQL responses as an extraction fallback
        intercepted_graphql = []
        def on_response(resp):
            if "graphql" in resp.url and resp.status == 200:
                try:
                    intercepted_graphql.append(resp.json())
                except Exception:
                    pass
        page.on("response", on_response)

        try:
            log(f"Navigating to {url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
        except PWTimeout:
            log("  [!] Navigation timed out. Proceeding to inspect rendered content...")
        except Exception as e:
            log(f"  [!] Navigation error: {e}")

        # Check for Cloudflare Turnstile / Challenge
        page.wait_for_timeout(2500)
        if is_challenge_active(page):
            log(f"  [!] Cloudflare Turnstile challenge detected. Monitoring for clearance (up to {max_wait}s)...")
            log("      (If running headed, solving the checkbox in the Chrome window will grant clearance)")
            t0 = time.time()
            while is_challenge_active(page) and (time.time() - t0 < max_wait):
                page.wait_for_timeout(2000)

        if is_challenge_active(page):
            log("  [!] Challenge was not cleared within the allotted time.")
            result["error"] = "Blocked by Cloudflare/DataDome challenge screen"
            context.close()
            out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

        log("  [+] Page reached successfully. Allowing client-side hydration...")
        page.wait_for_timeout(5000)

        # 1. Extract Product Title
        title = page.title()
        clean_title = re.sub(r"\s*-\s*US\s*$", "", title).strip()
        result["product_name"] = clean_title
        log(f"  [*] Product Title: {clean_title}")

        # 2. Extract from JSON-LD Structured Data (AggregateOffer)
        for blob in page.locator("script[type='application/ld+json']").all_text_contents():
            try:
                data = json.loads(blob)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if "sku" in item and not result["sku"]:
                    result["sku"] = item["sku"]

                offers = item.get("offers")
                if isinstance(offers, dict) and offers.get("@type") == "AggregateOffer":
                    low = offers.get("lowPrice")
                    high = offers.get("highPrice")
                    currency = offers.get("priceCurrency", "USD")
                    symbol = "$" if currency == "USD" else currency
                    
                    if low is not None:
                        result["current_market_price"] = f"{symbol}{low}"
                    if low is not None and high is not None:
                        result["price_range"] = f"{symbol}{low} - {symbol}{high}"

                    # Size-level breakdown
                    for sub in offers.get("offers", []):
                        desc = sub.get("description")
                        pr = sub.get("price")
                        if desc and pr:
                            result["size_offers"].append({
                                "size": str(desc),
                                "price": f"{symbol}{pr}"
                            })

        # 3. DOM Grounding for Last Sale, Buy Now, and Highest Bid / Sell Now
        body_text = page.inner_text("body")

        # Last Sale regex
        m_last = re.search(r"Last Sale[:\s]*(\$\s?[\d,]+)", body_text, re.I)
        if m_last:
            result["last_sale_price"] = m_last.group(1).replace(" ", "")

        # Lowest Ask / Buy Now regex
        if not result["current_market_price"]:
            m_ask = re.search(r"(?:Lowest Ask|Buy Now)[:\s]*(\$\s?[\d,]+)", body_text, re.I)
            if m_ask:
                result["current_market_price"] = m_ask.group(1).replace(" ", "")

        # Highest Bid / Sell Now
        m_bid = re.search(r"(?:Sell Now for|Highest Bid)[:\s]*(\$\s?[\d,]+)", body_text, re.I)
        if m_bid:
            result["highest_bid_price"] = m_bid.group(1).replace(" ", "")

        # 4. Fallback: Parse intercepted GraphQL data if needed
        if not result["current_market_price"]:
            for payload in intercepted_graphql:
                try:
                    product = payload.get("data", {}).get("product", {})
                    market = product.get("market", {})
                    ask = market.get("lowestAsk") or market.get("state", {}).get("lowestAsk")
                    if ask:
                        result["current_market_price"] = f"${ask}"
                        break
                except Exception:
                    pass

        # Final Status determination
        if result["current_market_price"] or result["last_sale_price"]:
            result["status"] = "success"
            log(f"  [+] Extraction SUCCESS!")
            log(f"      - Current Market Price (Lowest Ask): {result['current_market_price']}")
            log(f"      - Last Sale: {result['last_sale_price']}")
            log(f"      - Highest Bid: {result['highest_bid_price']}")
            log(f"      - Total Size Offers Indexed: {len(result['size_offers'])}")
        else:
            result["status"] = "failed"
            result["error"] = "Price elements not located on hydrated page"
            log("  [!] Failed to locate market price in DOM or structured data.")

        context.close()

    # Save output to output/stockx.json
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Results saved to: {out_file}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Live StockX Price Scraper")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Target StockX product URL")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--wait", type=int, default=45, help="Seconds to wait for challenge resolution")
    args = parser.parse_args()

    data = scrape_stockx(url=args.url, headless=args.headless, max_wait=args.wait)
    print("\n" + "="*50)
    print("STOCKX SCRAPING SUMMARY:")
    print("="*50)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
