"""
GreatClips Coupon Finder

Automatically discovers and filters Great Clips haircut coupons by area.
Searches Google, DuckDuckGo, and Bing for coupon aggregator sites, scrapes
them for coupon URLs, then checks each coupon page for area matches.

Author: Tanvir Hossain
Email:  jewel.tanvir@gmail.com, tanvir@ku.edu
Web:    https://www.tanvirhossain.net/
"""

import argparse
import logging
import re
import time
import unittest
from unittest.mock import patch, Mock
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from googlesearch import search

logger = logging.getLogger(__name__)

# Browser-like headers so sites don't block us as a bot.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Aggregator sites/pages known to list offers.greatclips.com coupon links.
KNOWN_AGGREGATORS = [
    "https://greatclipsdeal.com/",
    "https://coupons-greatclips.com/9-99",
    "https://coupons-greatclips.com/8-99",
    "https://coupons-greatclips.com/5-off",
    "https://coupons-greatclips.com/7-99",
    "https://coupons-greatclips.com/14-99",
]


def _make_session():
    """Create a requests session with browser-like headers."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


class GreatClipsScraper:
    BASE_URL = "https://offers.greatclips.com/"

    def __init__(self, target_area):
        self.target_area = target_area
        self.found_coupons = []
        self.session = _make_session()

    @staticmethod
    def _is_valid_coupon_url(url):
        """Validate that a URL is a proper offers.greatclips.com coupon link."""
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme in ("http", "https")
                and parsed.netloc == "offers.greatclips.com"
                and len(parsed.path) > 1  # more than just "/"
            )
        except Exception:
            return False

    def _matches_area(self, text):
        """Word-boundary match for target area to avoid false positives."""
        return bool(
            re.search(
                r'\b' + re.escape(self.target_area) + r'\b',
                text,
                re.IGNORECASE,
            )
        )

    def _extract_coupon_links_from_page(self, page_url):
        """Fetch a page and extract all offers.greatclips.com links from it."""
        links = []
        try:
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if self._is_valid_coupon_url(href):
                    links.append(href)
            logger.info(
                "Found %d coupon links on %s", len(links), page_url
            )
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error fetching %s: %s", page_url, e)
        except requests.exceptions.Timeout as e:
            logger.error("Timeout fetching %s: %s", page_url, e)
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error fetching %s: %s", page_url, e)
        except Exception as e:
            logger.error("Error fetching %s: %s", page_url, e)
        return links

    def _google_search(self, query, num_results=10):
        """Search Google for pages that mention offers.greatclips.com."""
        logger.info("Searching Google: %s", query)
        pages = []
        try:
            for url in search(query, num_results=num_results):
                parsed = urlparse(url)
                if parsed.netloc != "offers.greatclips.com":
                    pages.append(url)
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error during Google search: %s", e)
        except requests.exceptions.Timeout as e:
            logger.error("Timeout during Google search: %s", e)
        except Exception as e:
            logger.error("Google search error: %s", e)
        logger.info("Google returned %d pages", len(pages))
        return pages

    def _duckduckgo_search(self, query, num_results=10):
        """Search DuckDuckGo for pages that mention offers.greatclips.com."""
        logger.info("Searching DuckDuckGo: %s", query)
        pages = []
        try:
            results = DDGS().text(query, max_results=num_results)
            for r in results:
                url = r.get("href", "")
                if url:
                    parsed = urlparse(url)
                    if parsed.netloc != "offers.greatclips.com":
                        pages.append(url)
        except Exception as e:
            logger.error("DuckDuckGo search error: %s", e)
        logger.info("DuckDuckGo returned %d pages", len(pages))
        return pages

    def _bing_search(self, query, num_results=10):
        """Scrape Bing search results for pages mentioning offers.greatclips.com."""
        logger.info("Searching Bing: %s", query)
        pages = []
        try:
            url = (
                f"https://www.bing.com/search"
                f"?q={requests.utils.quote(query)}&count={num_results}"
            )
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                parsed = urlparse(href)
                if (
                    parsed.scheme in ("http", "https")
                    and parsed.netloc
                    and "bing.com" not in parsed.netloc
                    and "microsoft.com" not in parsed.netloc
                    and parsed.netloc != "offers.greatclips.com"
                ):
                    pages.append(href)
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error during Bing search: %s", e)
        except requests.exceptions.Timeout as e:
            logger.error("Timeout during Bing search: %s", e)
        except Exception as e:
            logger.error("Bing search error: %s", e)
        logger.info("Bing returned %d pages", len(pages))
        return pages

    def discover_coupons(self, num_results=10):
        """
        Discover coupon URLs by:
        1. Searching multiple engines for pages that link to offers.greatclips.com
        2. Scraping those pages + known aggregators for coupon URLs
        3. Deduplicating results
        """
        logger.info("Discovering coupon URLs...")
        query = '"offers.greatclips.com" coupon'

        # Step 1: Gather aggregator pages from multiple search engines
        aggregator_pages = []

        google_pages = self._google_search(query, num_results)
        aggregator_pages.extend(google_pages)
        time.sleep(2)

        ddg_pages = self._duckduckgo_search(query, num_results)
        aggregator_pages.extend(ddg_pages)
        time.sleep(2)

        bing_pages = self._bing_search(query, num_results)
        aggregator_pages.extend(bing_pages)

        # Step 2: Add known aggregators
        all_pages = list(aggregator_pages)
        for known in KNOWN_AGGREGATORS:
            if known not in all_pages:
                all_pages.append(known)

        # Deduplicate pages
        seen_pages = set()
        unique_pages = []
        for p in all_pages:
            if p not in seen_pages:
                seen_pages.add(p)
                unique_pages.append(p)

        logger.info(
            "Total aggregator pages to scrape: %d (%d from search + %d known)",
            len(unique_pages),
            len(unique_pages) - len(KNOWN_AGGREGATORS),
            len(KNOWN_AGGREGATORS),
        )

        # Step 3: Scrape each page for coupon links
        all_coupon_urls = []
        for page_url in unique_pages:
            coupon_links = self._extract_coupon_links_from_page(page_url)
            all_coupon_urls.extend(coupon_links)
            time.sleep(1)

        # Deduplicate coupon URLs
        seen = set()
        unique = []
        for url in all_coupon_urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        if unique:
            logger.info("Discovered %d unique coupon URLs total", len(unique))
        else:
            logger.warning("No coupon URLs discovered from any source.")

        return unique

    def extract_coupon_details(self, url):
        """Extract area names and offer details from a specific coupon page."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            description_text = ""
            terms_text = ""

            offer_details = soup.find('div', id='offer-details')
            if offer_details:
                current_section = None
                for tag in offer_details.descendants:
                    if tag.name == 'h4':
                        heading = tag.get_text(strip=True).lower()
                        if 'description' in heading:
                            current_section = 'description'
                        elif 'term' in heading:
                            current_section = 'terms'
                        else:
                            current_section = None
                    elif hasattr(tag, 'get_text') and tag.name in (
                        'p', 'div', 'span', 'li',
                    ):
                        text = tag.get_text(strip=True)
                        if text:
                            if current_section == 'description':
                                description_text += " " + text
                            elif current_section == 'terms':
                                terms_text += " " + text
            else:
                logger.warning(
                    "No #offer-details found on %s; falling back to body text", url
                )
                body = soup.find('body')
                description_text = body.get_text(strip=True) if body else ""

            description_text = description_text.strip()
            terms_text = terms_text.strip()

            # Combine text for matching
            all_text = f"{description_text} {terms_text}"

            # Extract offer value (e.g., $9.99 or $2 off) from combined text
            offer_value = "Unknown"
            match = re.search(
                r'\$\d+(?:\.\d{2})?(?:\s*off)?', all_text, re.IGNORECASE
            )
            if match:
                offer_value = match.group(0)

            return {
                'url': url,
                'area_text': all_text,
                'offer_value': offer_value,
                'is_target': self._matches_area(all_text),
            }
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error extracting %s: %s", url, e)
            return None
        except requests.exceptions.Timeout as e:
            logger.error("Timeout extracting %s: %s", url, e)
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error extracting %s: %s", url, e)
            return None
        except (AttributeError, TypeError) as e:
            logger.error("Parse error extracting %s: %s", url, e)
            return None
        except Exception as e:
            logger.error("Unexpected error extracting %s: %s", url, e)
            return None

    def run(self, limit=10):
        urls = self.discover_coupons(num_results=limit)
        if not urls:
            return self.found_coupons

        logger.info(
            "Found %d potential coupon URLs. Scraping details...", len(urls)
        )

        total = len(urls)
        for i, url in enumerate(urls, 1):
            print(
                f"\r  Checking coupon {i}/{total} "
                f"({len(self.found_coupons)} matches so far)...",
                end="", flush=True,
            )
            details = self.extract_coupon_details(url)
            if details and details['is_target']:
                logger.info(
                    "\nFOUND MATCH: %s (%s) for %s",
                    url, details['offer_value'], self.target_area,
                )
                self.found_coupons.append(details)
            time.sleep(1)  # Be polite

        print()  # newline after progress

        if not self.found_coupons:
            logger.info("No coupons found for area: '%s'", self.target_area)

        return self.found_coupons


# ---------------------------------------------------------------------------
# Tests (run with: python scraper.py --test)
# ---------------------------------------------------------------------------

WILMINGTON_HTML = """
<html>
<body>
<div id="offer-details">
    <h4>Description</h4>
    <p>$8.99 Haircut for the Wilmington, DE area.</p>
    <h4>Terms and Conditions</h4>
    <p>Valid at participating salons in Wilmington, Delaware only.</p>
    <p>Limit one coupon per customer. Not valid with other offers.</p>
</div>
</body>
</html>
"""

NO_AREA_HTML = """
<html>
<body>
<div id="offer-details">
    <h4>Description</h4>
    <p>$2 off any haircut service.</p>
    <h4>Terms and Conditions</h4>
    <p>Valid at participating salons nationwide.</p>
</div>
</body>
</html>
"""

NO_OFFER_DETAILS_HTML = """
<html>
<body>
<p>Some generic page content about haircuts in Wilmington.</p>
</body>
</html>
"""

VALUE_IN_TERMS_HTML = """
<html>
<body>
<div id="offer-details">
    <h4>Description</h4>
    <p>Special haircut offer for Springfield, IL area.</p>
    <h4>Terms and Conditions</h4>
    <p>Get $5.99 off your next visit. Valid at Springfield locations.</p>
</div>
</body>
</html>
"""

AGGREGATOR_HTML = """
<html>
<body>
<h1>Great Clips Coupons</h1>
<ul>
    <li><a href="https://offers.greatclips.com/abc1234">Coupon 1</a></li>
    <li><a href="https://offers.greatclips.com/xyz5678">Coupon 2</a></li>
    <li><a href="https://offers.greatclips.com/abc1234">Coupon 1 (duplicate)</a></li>
    <li><a href="https://www.example.com/not-a-coupon">Other link</a></li>
</ul>
</body>
</html>
"""


def _mock_response(html, status_code=200):
    resp = Mock()
    resp.status_code = status_code
    resp.text = html
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
    return resp


class TestAreaMatching(unittest.TestCase):

    def test_exact_match(self):
        scraper = GreatClipsScraper("Wilmington")
        self.assertTrue(scraper._matches_area("Valid in Wilmington, DE only"))

    def test_case_insensitive(self):
        scraper = GreatClipsScraper("wilmington")
        self.assertTrue(scraper._matches_area("WILMINGTON area"))

    def test_no_match(self):
        scraper = GreatClipsScraper("Kansas City")
        self.assertFalse(scraper._matches_area("Valid in Wilmington, DE only"))

    def test_word_boundary_prevents_substring(self):
        scraper = GreatClipsScraper("DC")
        self.assertFalse(scraper._matches_area("EDUCATION program"))
        self.assertTrue(scraper._matches_area("Washington DC area"))

    def test_multi_word_area(self):
        scraper = GreatClipsScraper("Kansas City")
        self.assertTrue(scraper._matches_area("Offer for Kansas City, MO"))
        self.assertFalse(scraper._matches_area("Offer for Kansas state"))


class TestURLValidation(unittest.TestCase):

    def test_valid_https(self):
        self.assertTrue(
            GreatClipsScraper._is_valid_coupon_url(
                "https://offers.greatclips.com/7GqMiDg"
            )
        )

    def test_valid_http(self):
        self.assertTrue(
            GreatClipsScraper._is_valid_coupon_url(
                "http://offers.greatclips.com/abc123"
            )
        )

    def test_invalid_domain(self):
        self.assertFalse(
            GreatClipsScraper._is_valid_coupon_url(
                "https://www.greatclips.com/coupons"
            )
        )

    def test_root_path_only(self):
        self.assertFalse(
            GreatClipsScraper._is_valid_coupon_url(
                "https://offers.greatclips.com/"
            )
        )

    def test_no_scheme(self):
        self.assertFalse(
            GreatClipsScraper._is_valid_coupon_url(
                "offers.greatclips.com/abc"
            )
        )

    def test_empty_string(self):
        self.assertFalse(GreatClipsScraper._is_valid_coupon_url(""))

    def test_nonsense(self):
        self.assertFalse(GreatClipsScraper._is_valid_coupon_url("not a url"))


class TestExtractCouponDetails(unittest.TestCase):

    def _make_scraper(self, area, mock_session_get):
        scraper = GreatClipsScraper(area)
        scraper.session = Mock()
        scraper.session.get = mock_session_get
        return scraper

    def test_wilmington_area_match(self):
        mock_get = Mock(return_value=_mock_response(WILMINGTON_HTML))
        scraper = self._make_scraper("Wilmington", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/7GqMiDg"
        )
        self.assertIsNotNone(details)
        self.assertTrue(details["is_target"])
        self.assertEqual(details["offer_value"], "$8.99")

    def test_non_matching_area(self):
        mock_get = Mock(return_value=_mock_response(WILMINGTON_HTML))
        scraper = self._make_scraper("Kansas City", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/7GqMiDg"
        )
        self.assertIsNotNone(details)
        self.assertFalse(details["is_target"])

    def test_dollar_off_extraction(self):
        mock_get = Mock(return_value=_mock_response(NO_AREA_HTML))
        scraper = self._make_scraper("Anywhere", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/xyz"
        )
        self.assertIsNotNone(details)
        self.assertEqual(details["offer_value"], "$2 off")

    def test_value_in_terms_section(self):
        mock_get = Mock(return_value=_mock_response(VALUE_IN_TERMS_HTML))
        scraper = self._make_scraper("Springfield", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/abc"
        )
        self.assertIsNotNone(details)
        self.assertTrue(details["is_target"])
        self.assertEqual(details["offer_value"], "$5.99 off")

    def test_fallback_when_no_offer_details_div(self):
        mock_get = Mock(return_value=_mock_response(NO_OFFER_DETAILS_HTML))
        scraper = self._make_scraper("Wilmington", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/fallback"
        )
        self.assertIsNotNone(details)
        self.assertTrue(details["is_target"])
        self.assertEqual(details["offer_value"], "Unknown")

    def test_http_error_returns_none(self):
        mock_get = Mock(return_value=_mock_response("", status_code=404))
        scraper = self._make_scraper("Wilmington", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/gone"
        )
        self.assertIsNone(details)

    def test_connection_error_returns_none(self):
        mock_get = Mock(
            side_effect=requests.exceptions.ConnectionError("refused")
        )
        scraper = self._make_scraper("Wilmington", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/err"
        )
        self.assertIsNone(details)

    def test_timeout_returns_none(self):
        mock_get = Mock(
            side_effect=requests.exceptions.Timeout("timed out")
        )
        scraper = self._make_scraper("Wilmington", mock_get)
        details = scraper.extract_coupon_details(
            "https://offers.greatclips.com/slow"
        )
        self.assertIsNone(details)


class TestExtractCouponLinksFromPage(unittest.TestCase):

    def test_extracts_valid_links(self):
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.return_value = _mock_response(AGGREGATOR_HTML)
        links = scraper._extract_coupon_links_from_page("https://example.com")
        self.assertEqual(len(links), 3)
        self.assertIn("https://offers.greatclips.com/abc1234", links)
        self.assertIn("https://offers.greatclips.com/xyz5678", links)

    def test_connection_error_returns_empty(self):
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.side_effect = requests.exceptions.ConnectionError(
            "refused"
        )
        links = scraper._extract_coupon_links_from_page("https://example.com")
        self.assertEqual(links, [])

    def test_no_coupon_links_returns_empty(self):
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.return_value = _mock_response(
            "<html><body><a href='https://example.com'>nope</a></body></html>"
        )
        links = scraper._extract_coupon_links_from_page("https://example.com")
        self.assertEqual(links, [])


class TestDiscoverCoupons(unittest.TestCase):

    @patch("__main__.time.sleep")
    @patch("__main__.DDGS")
    @patch("__main__.search")
    def test_combines_all_sources(self, mock_google, mock_ddgs_cls, mock_sleep):
        mock_google.return_value = iter(["https://deal-site.com/coupons"])
        mock_ddgs_inst = Mock()
        mock_ddgs_cls.return_value = mock_ddgs_inst
        mock_ddgs_inst.text.return_value = [
            {"href": "https://another-site.com/deals"}
        ]
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.return_value = _mock_response(
            '<html><body><a href="https://offers.greatclips.com/aaa">A</a></body></html>'
        )
        urls = scraper.discover_coupons(num_results=5)
        self.assertIn("https://offers.greatclips.com/aaa", urls)
        mock_google.assert_called_once()
        mock_ddgs_inst.text.assert_called_once()

    @patch("__main__.time.sleep")
    @patch("__main__.DDGS")
    @patch("__main__.search")
    def test_deduplicates_urls(self, mock_google, mock_ddgs_cls, mock_sleep):
        mock_google.return_value = iter([])
        mock_ddgs_inst = Mock()
        mock_ddgs_cls.return_value = mock_ddgs_inst
        mock_ddgs_inst.text.return_value = []
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.return_value = _mock_response(AGGREGATOR_HTML)
        urls = scraper.discover_coupons(num_results=5)
        self.assertEqual(urls.count("https://offers.greatclips.com/abc1234"), 1)

    @patch("__main__.time.sleep")
    @patch("__main__.DDGS")
    @patch("__main__.search")
    def test_all_engines_fail_still_uses_known_aggregators(
        self, mock_google, mock_ddgs_cls, mock_sleep
    ):
        mock_google.side_effect = Exception("rate limited")
        mock_ddgs_cls.side_effect = Exception("blocked")
        scraper = GreatClipsScraper("Test")
        scraper.session = Mock()
        scraper.session.get.return_value = _mock_response(AGGREGATOR_HTML)
        urls = scraper.discover_coupons(num_results=5)
        self.assertTrue(len(urls) > 0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Great Clips Coupon Finder")
    parser.add_argument(
        "--area",
        help="Specific area to search for (e.g., 'Kansas City')",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Number of search results per engine to check",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run unit tests instead of scraping",
    )

    args = parser.parse_args()

    if args.test:
        # Remove our custom args so unittest doesn't choke on them
        import sys
        sys.argv = [sys.argv[0]]
        unittest.main(module=__name__, verbosity=2)
    else:
        if not args.area:
            parser.error("--area is required when not running tests")
        scraper = GreatClipsScraper(args.area)
        results = scraper.run(limit=args.limit)

        if results:
            print("\n=== Matched Coupons ===")
            for r in results:
                print(f"URL: {r['url']}")
                print(f"Offer: {r['offer_value']}")
                print("-" * 20)
