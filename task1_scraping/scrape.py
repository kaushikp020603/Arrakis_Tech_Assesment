"""Task 1 - scrape 5 live sites to JSON (one file per site).

Usage:
    python scrape.py                 # all sites
    python scrape.py indeed g2       # selected sites

Runs a visible (headed) Chromium with a persistent profile. Most of these sites
sit behind bot protection. If a challenge/CAPTCHA appears, solve it yourself in
the window; the script waits for it to clear. The script never tries to bypass
CAPTCHAs.
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "output"
PROFILE = Path(__file__).parent / ".profile"
CHALLENGE_WORDS = ("just a moment", "verify you are human", "captcha",
                   "access denied", "press & hold", "are you a robot",
                   "security check", "blocked")
MAX_WAIT_FOR_HUMAN = 180  # seconds
HUMAN_MS = MAX_WAIT_FOR_HUMAN * 1000


def blocked(page):
    try:
        text = (page.title() + " " + page.inner_text("body")[:600]).lower()
    except Exception:
        return False
    return any(w in text for w in CHALLENGE_WORDS)


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    print(f"  (if the page shows a CAPTCHA/verification, solve it in the window; "
          f"waiting up to {MAX_WAIT_FOR_HUMAN}s for results)")
    if blocked(page):
        print(f"  [!] challenge on {url} - solve it in the browser window "
              f"(waiting up to {MAX_WAIT_FOR_HUMAN}s)")
        t0 = time.time()
        while blocked(page) and time.time() - t0 < MAX_WAIT_FOR_HUMAN:
            page.wait_for_timeout(2000)
        page.wait_for_timeout(2000)
    return not blocked(page)


def first_text(el, selectors):
    for s in selectors:
        try:
            loc = el.locator(s).first
            if loc.count():
                t = loc.inner_text(timeout=1500).strip()
                if t:
                    return t
        except Exception:
            continue
    return None


def indeed(page):
    url = "https://www.indeed.com/jobs?q=python+developer&l=Mumbai"
    if not goto(page, url):
        return None
    page.wait_for_selector("div.job_seen_beacon, [data-testid='slider_item']",
                           timeout=HUMAN_MS)
    jobs = []
    cards = page.locator("div.job_seen_beacon")
    if not cards.count():
        cards = page.locator("[data-testid='slider_item']")
    for card in cards.all():
        title = first_text(card, ["h3.jobTitle span[title]", "h2.jobTitle", "h2 a span",
                                  "[data-testid='jobTitle']"])
        company = first_text(card, ["[data-testid='company-name']", ".companyName"])
        if title:
            jobs.append({"job_title": title, "company": company})
    return jobs


def glassdoor(page):
    url = "https://www.glassdoor.com/Reviews/Google-Reviews-E9079.htm"
    if not goto(page, url):
        return None
    page.wait_for_selector("script[type='application/ld+json']", state="attached",
                           timeout=HUMAN_MS)
    page.wait_for_timeout(3000)
    reviews = []
    # Reviews are published as schema.org Review objects in JSON-LD (public structured data).
    for blob in page.locator("script[type='application/ld+json']").all_text_contents():
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "Review":
                rating = (item.get("reviewRating") or {}).get("ratingValue")
                title = item.get("name") or item.get("headline")
                if title or rating:
                    reviews.append({"review_title": title, "star_rating": rating})
    return reviews


def zillow(page):
    url = "https://www.zillow.com/homes/for_sale/"
    if not goto(page, url):
        return None
    page.wait_for_selector("article[data-test='property-card'], li article",
                           timeout=HUMAN_MS)
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(1500)
    out = []
    for c in page.locator("article[data-test='property-card'], li article").all():
        price = first_text(c, ["[data-test='property-card-price']", "span[class*='price']"])
        addr = first_text(c, ["address", "[data-test='property-card-addr']"])
        if price or addr:
            out.append({"price": price, "address": addr})
    return out


def g2(page):
    # The category slug in the assessment (endpoint-detection-and-response) is a 404 on G2;
    # the live EDR category is endpoint-detection-response-edr.
    url = "https://www.g2.com/categories/endpoint-detection-response-edr"
    if not goto(page, url):
        return None
    # G2 sometimes returns a blank 403 to automation; refresh / solve it in the window if so.
    page.wait_for_function(r"/\d(\.\d)?\/5/.test(document.body.innerText)",
                           timeout=HUMAN_MS)
    page.wait_for_timeout(1500)
    return page.evaluate(r"""() => {
        const out = [], seen = new Set();
        const ratingEls = [...document.querySelectorAll('*')].filter(
            e => e.childElementCount === 0 && /^\d(\.\d)?\/5$/.test(e.textContent.trim()));
        for (const r of ratingEls) {
            let n = r, link = null;
            for (let i = 0; i < 10 && n && !link; i++) {
                n = n.parentElement;
                if (!n) break;
                link = [...n.querySelectorAll('a[href*="/products/"]')]
                    .find(a => a.innerText.trim().length > 2 && !/try for free|reviews?$/i.test(a.innerText.trim()));
            }
            if (!link) continue;
            const name = link.innerText.trim();
            if (seen.has(name)) continue;
            seen.add(name);
            out.push({product_name: name, star_rating: r.textContent.trim()});
        }
        return out;
    }""")


def stockx(page):
    url = "https://stockx.com/nike-air-force-1-low-white-white"
    if not goto(page, url):
        return None
    page.wait_for_timeout(4000)
    t0 = time.time()
    while "air force" not in page.title().lower() and time.time() - t0 < MAX_WAIT_FOR_HUMAN:
        page.wait_for_timeout(2000)  # give a human time to clear the challenge
    if "air force" not in page.title().lower():
        return None  # landed on a generic/blocked page, not the product listing
    body = page.inner_text("body")
    # Prefer structured data, fall back to the first "$123" shown near "Last Sale"/"Lowest Ask"
    price = None
    for blob in page.locator("script[type='application/ld+json']").all_text_contents():
        m = re.search(r'"(?:lowPrice|price)"\s*:\s*"?(\d+(?:\.\d+)?)', blob)
        if m:
            price = "$" + m.group(1)
            break
    if not price:
        m = re.search(r"(?:Last Sale|Lowest Ask)[^$]{0,40}(\$\s?[\d,]+)", body, re.I)
        price = m.group(1) if m else None
    return {"product": page.title(), "current_market_price": price}


SITES = {"indeed": indeed, "glassdoor": glassdoor, "zillow": zillow,
         "g2": g2, "stockx": stockx}


def main():
    wanted = sys.argv[1:] or list(SITES)
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="chrome", headless=False, viewport={"width": 1366, "height": 850},
            locale="en-US")
        page = ctx.new_page()
        for name in wanted:
            print(f"[{name}] scraping...")
            record = {"site": name, "status": "ok", "data": None}
            try:
                data = SITES[name](page)
                if data is None:
                    record.update(status="blocked",
                                  note="bot challenge not cleared; no data collected")
                elif not data:
                    record.update(status="empty",
                                  note="page loaded but selectors matched nothing")
                else:
                    record["data"] = data
            except PWTimeout:
                record.update(status="timeout",
                              note="expected elements never appeared (blocked or layout changed)")
            except Exception as e:  # keep going so one site does not stop the rest
                record.update(status="error", note=f"{type(e).__name__}: {e}")
            (OUT / f"{name}.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            n = len(record["data"]) if isinstance(record["data"], list) else int(bool(record["data"]))
            print(f"  -> {record['status']} ({n} records) saved to output/{name}.json")
        ctx.close()


if __name__ == "__main__":
    main()
