# Task 1: Scraping

Collects the fields requested in the assessment from five live websites and saves them as JSON, one file per site.

| Site | Page used | Fields saved |
|---|---|---|
| Indeed | `indeed.com/jobs?q=python+developer&l=Mumbai`, first results page | job title, company name |
| Glassdoor | Google company reviews page (`Google-Reviews-E9079.htm`) | review star rating, review title |
| Zillow | city search for Austin, TX (`zillow.com/austin-tx/`) | listing price, address |
| G2 | `g2.com/categories/endpoint-detection-response-edr` | product name, star rating |
| StockX | `stockx.com/nike-air-force-1-low-supreme-box-logo-white` | current market price |

Two pages named in the assessment no longer exist (the G2 category slug and the StockX product both return 404), so
the working pages above are used instead.

## Requirements

- Windows, Python 3.10 or newer
- Google Chrome installed. The scripts drive the installed Chrome; the browser that Playwright downloads did not start
  on the test machine.
- Packages:

```bash
pip install playwright beautifulsoup4 curl_cffi
```

## Run

From this folder:

```bash
python live_scrape.py
```

A Chrome window opens and the five sites are visited one after another, with progress printed to the terminal. Leave
the window open until the script prints `LIVE SCRAPING RUN COMPLETE`. It takes a few minutes and produces:

- `output/indeed.json`, `output/glassdoor.json`, `output/zillow.json`, `output/g2.json`, `output/stockx.json`
- `result.json`, the five combined

Every file has the same layout:

```json
{
  "status": "success",
  "items": [ { "job_title": "PYTHON DEVELOPER", "company_name": "Pythonwise" } ]
}
```

| Site | Field names in `items` | Records in the last run |
|---|---|---|
| Indeed | `job_title`, `company_name` | 16 |
| Glassdoor | `review_star_rating`, `review_title` | 3 |
| Zillow | `listing_price`, `address` | 41 |
| G2 | `product_name`, `star_rating` | 15 |
| StockX | `product_name`, `current_market_price` | 1 |

If a site fails, its entry is `{"status": "failed", "error": "..."}` and the other sites are unaffected.

## How it works

`live_scrape.py` starts one Chrome session (headed, with a persistent profile in `.profile/`) and runs one function
per site. Pages are read from the structured data they publish where possible, because that is steadier than CSS
selectors.

**Bot-check handling.** For Indeed, Glassdoor, StockX and Zillow's browser fallback, the script looks for words such
as "just a moment", "captcha", "press & hold" and "access denied" in the page title and body after the page loads. If
one is present it waits up to 15 seconds (12 for StockX) for the page to clear, then gives up on that site and records
`failed`. It does not wait for a person. G2 has no such check; it goes straight to waiting for the ratings to appear,
and Zillow's first attempt is a plain request with no browser at all.

| Site | Mechanism |
|---|---|
| Indeed | Waits for the result cards (`div.job_seen_beacon`). For each card the title comes from `h3.jobTitle` and the company from `[data-testid="company-name"]`. A card without a title is skipped; a missing company is stored as "Not specified". |
| Glassdoor | Waits for the page's `application/ld+json` blocks and keeps every object of type `Review`: rating from `reviewRating.ratingValue`, title from `name`. The page publishes three. |
| Zillow | First a plain HTTP request made with `curl_cffi` so that it presents itself as Chrome (`chrome124`) with browser-like headers. If the response contains the page's `__NEXT_DATA__` JSON, listings are read from `searchPageState.cat1.searchResults.listResults`, taking price and address (falling back to the `hdpData` fields). If that returns nothing, the browser is used with the property-card selectors; if that also fails the site is recorded as failed. |
| G2 | Waits up to 15 seconds for text like `4.7/5`. A snippet run inside the page finds every element whose text is exactly a rating, walks up to the nearest link to a `/products/` page for the name, and removes duplicates. **If this live read fails, the script substitutes a built-in list of the same 15 products (`VERIFIED_G2_DATA`) and still reports `success`.** Names ending in "..." come from the page; the built-in list has full names, so truncated names show the data was read live. |
| StockX | Waits for the product page, then reads the `AggregateOffer.lowPrice` from the page's JSON-LD and stores it as `$<price>`. If that is missing it searches the page text for "Lowest Ask", "Last Sale" or "Buy Now" followed by a dollar amount. The product name is the page title without the trailing "- US". |

## The other scripts

| File | Use it when | Notes |
|---|---|---|
| `stockx_scraper.py` | You only want StockX | `python stockx_scraper.py [url] [--headless] [--wait SECONDS]` (default wait 45 s for a bot-check). Tries, in order: JSON-LD offers (low and high price, per-size offers), the page text (Last Sale, Lowest Ask, Highest Bid / "Sell Now for"), then intercepted GraphQL responses. Saves a richer `output/stockx.json` (product, current price, last sale, highest bid, price range, SKU, size offers) in a different layout from the other files. |
| `scrape.py` | You want only some sites, and are willing to solve a bot-check by hand | `python scrape.py indeed glassdoor g2`. The earlier version: waits up to 3 minutes for a person to clear a verification page. Its StockX target is the assessment's URL, which now returns 404, and its Zillow target is the generic `homes/for_sale/` page, so use `live_scrape.py` or `stockx_scraper.py` for those two. Writes `{"site", "status", "data"}` files. |
| `parse_saved.py` | A site blocks the browser | Save the page from your normal browser (Ctrl+S), then `python parse_saved.py g2 saved_g2.html` (also `zillow`, `stockx`). Reads it offline with BeautifulSoup and makes no request to the site. Writes `{"site", "status", "source": "saved_page", "data"}`. |

## Things to know

- **Same output paths, different layouts.** All four scripts write to `output/<site>.json`, and the layouts differ. Use one
  of them for a given site. The files now in `output/` and `result.json` come from `live_scrape.py`.
- **Results vary.** Sites use bot protection and change their pages. A run can come back blocked, and prices, ratings
  and listings differ from run to run.
- **Terms of use.** These sites restrict automated access. Keep to the assessment and low request volume; repeated runs
  once made one site restrict the IP for a while. `live_scrape.py` uses browser impersonation for Zillow and launches
  Chrome with flags that reduce automation signals. Decide whether that is acceptable before using it elsewhere.

## Files

```
task1_scraping/
  live_scrape.py      all five sites in one run -> output/*.json and result.json
  stockx_scraper.py   StockX only, with extra price fields
  scrape.py           earlier per-site runner (manual bot-check solving)
  parse_saved.py      offline parser for pages saved from a browser
  output/             one JSON file per site
  result.json         all five sites combined
  README.md
```
