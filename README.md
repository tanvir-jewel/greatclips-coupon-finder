# GreatClips Coupon Finder

A Python tool that automatically discovers and filters Great Clips haircut coupons by area.

Since `offers.greatclips.com` blocks search engine indexing and has no public listing page, this tool searches Google, DuckDuckGo, and Bing for coupon aggregator sites, scrapes them for coupon URLs, then checks each coupon page to find deals matching your area.

## Setup

```bash
pip install requests beautifulsoup4 lxml googlesearch-python ddgs
```

## Usage

```bash
python scraper.py --area "Eastern Carolina"              # uses default limit of 20
python scraper.py --area "Kansas City"                   # default limit (20 results per search engine)
python scraper.py --area "Kansas City" --limit 15        # custom limit
```

The `--limit` flag is optional. If omitted, it defaults to 20 results per search engine.

| Argument  | Required | Default | Description                              |
|-----------|----------|---------|------------------------------------------|
| `--area`  | Yes      | —       | Area name to match (e.g. "Wilmington")   |
| `--limit` | No       | 20      | Search results per engine to check       |

## How It Works

1. **Search** — Queries 3 search engines for sites that link to `offers.greatclips.com`
2. **Scrape** — Visits each aggregator page and extracts coupon URLs
3. **Filter** — Checks each coupon page for your target area (word-boundary matching)
4. **Report** — Prints matching coupons with their offer value and URL

Known aggregator sites are included as fallback sources in case search engines are rate-limited.

## Tests

```bash
python scraper.py --test
```

All tests use mocked HTTP responses — no live network calls.

## Author

Tanvir Hossain
- Email: jewel.tanvir@gmail.com, tanvir@ku.edu
- Web: https://www.tanvirhossain.net/
