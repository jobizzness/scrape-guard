import xml.etree.ElementTree as ET
from collections import deque
from functools import partial
from typing import Any
from urllib.parse import urljoin

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .models import Quote, Row, Trend
from .retry import fetch_text, retry

QUOTES_URL = "https://quotes.toscrape.com/"
SCROLL_URL = "https://quotes.toscrape.com/scroll"
TRENDS_URL = "https://trends.google.com/trending/rss"
API_PATH = "/api/quotes"
MAX_PAGES = 20
MAX_STALLS = 3
NAV_TIMEOUT_MS = 15_000
STALL_MS = 3_000


# A card missing a field yields "" instead of blocking until Playwright's timeout.
def first_text(locator: Locator) -> str:
    texts = locator.all_inner_texts()
    return texts[0].strip() if texts else ""


def extract_quotes(page: Page, quote_class: str = "quote") -> tuple[list[Quote], str | None]:
    quotes = [
        Quote(
            text=first_text(card.locator(".text")),
            author=first_text(card.locator(".author")),
            tags=[tag.strip() for tag in card.locator(".tag").all_inner_texts()],
        )
        for card in page.locator(f".{quote_class}").all()
    ]
    link = page.locator("li.next a")
    return quotes, link.get_attribute("href") if link.count() else None


# Raise on a bad status so retry() treats it like any other transient failure.
def open_page(page: Page, url: str) -> None:
    response = page.goto(url, timeout=NAV_TIMEOUT_MS)
    if response is None or not response.ok:
        raise PlaywrightError(f"bad response for {url}")


def is_api(response: Response) -> bool:
    return API_PATH in response.url


# A timeout here is not an error: it means this scroll brought no new data.
def scroll_to_bottom(page: Page, stall_ms: int) -> None:
    try:
        with page.expect_response(is_api, timeout=stall_ms):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except PlaywrightTimeout:
        pass


def scroll_quotes(page: Page, url: str, stall_ms: int = STALL_MS) -> list[Quote]:
    # Read the page's own API responses rather than its DOM: the data arrives structured
    # and nothing breaks when the markup changes.
    arrived: deque[Response] = deque()
    # Keyed by page number, so a response that arrives twice adds nothing.
    pages: dict[int, dict[str, Any]] = {}
    page.on("response", lambda response: arrived.append(response) if is_api(response) else None)
    retry(partial(open_page, page, url))
    # Stop at the last page, or after MAX_STALLS scrolls with nothing new. The second exit
    # returns partial rows on purpose: the guard is what turns that into an alert.
    stalls = 0
    while stalls < MAX_STALLS and not (pages and not pages[max(pages)].get("has_next")):
        known = len(pages)
        scroll_to_bottom(page, stall_ms)
        while arrived:
            response = arrived.popleft()
            if response.ok:
                data = response.json()
                pages[data["page"]] = data
        stalls = 0 if len(pages) > known else stalls + 1
    return [
        Quote(item["text"], item.get("author", {}).get("name", ""), item.get("tags", []))
        for _, data in sorted(pages.items())
        for item in data["quotes"]
    ]


def parse_trends(xml_text: str) -> list[Trend]:
    trends = []
    for item in ET.fromstring(xml_text).iter("item"):
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
        trends.append(
            Trend(
                title=values.get("title", ""),
                approx_traffic=values.get("approx_traffic", ""),
                published=values.get("pubDate", ""),
            )
        )
    return trends


class QuotesSource:
    name = "quotes"
    required = ("text", "author")

    def __init__(self, quote_class: str = "quote") -> None:
        self.quote_class = quote_class

    def fetch(self) -> list[Row]:
        rows: list[Row] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            url = QUOTES_URL
            # Bounded, so a pagination loop on the site can't run forever.
            for _ in range(MAX_PAGES):
                retry(partial(open_page, page, url))
                quotes, href = extract_quotes(page, self.quote_class)
                rows.extend(quotes)
                if href is None:
                    break
                url = urljoin(url, href)
            browser.close()
        return rows


class ScrollSource:
    name = "scroll"
    required = ("text", "author")

    def __init__(self, url: str = SCROLL_URL) -> None:
        self.url = url

    def fetch(self) -> list[Row]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            rows: list[Row] = list(scroll_quotes(browser.new_page(), self.url))
            browser.close()
        return rows


class TrendsSource:
    name = "trends"
    required = ("title", "approx_traffic", "published")

    def __init__(self, geo: str = "US") -> None:
        self.geo = geo

    def fetch(self) -> list[Row]:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            return list(parse_trends(fetch_text(client, f"{TRENDS_URL}?geo={self.geo}")))
