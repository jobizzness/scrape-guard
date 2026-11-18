import json
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Error, Page, Route, sync_playwright

from scrape_guard.models import Quote
from scrape_guard.sources import extract_quotes, parse_trends, scroll_quotes

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Error:
            pytest.skip("Chromium is not installed")
        yield instance
        instance.close()


@pytest.fixture(scope="module")
def page(browser: Browser) -> Page:
    return browser.new_page()


SCROLL_URL = "https://site.test/scroll"


@pytest.fixture
def fresh_page(browser: Browser) -> Iterator[Page]:
    fresh = browser.new_page()
    yield fresh
    fresh.close()


def serve_scroll(page: Page, last_page: int = 10, stop_after: int = 10) -> list[int]:
    requested: list[int] = []

    def handle(route: Route) -> None:
        url = urlparse(route.request.url)
        if url.path == "/scroll":
            route.fulfill(body=(FIXTURES / "scroll.html").read_text(), content_type="text/html")
            return
        number = int(parse_qs(url.query)["page"][0])
        if number > stop_after:
            route.abort()
            return
        requested.append(number)
        quotes = [{"text": f"q{number}-{i}", "author": {"name": "A"}, "tags": ["t"]} for i in range(10)]
        body = {"page": number, "has_next": number < last_page, "quotes": quotes}
        route.fulfill(body=json.dumps(body), content_type="application/json")

    page.route("https://site.test/**", handle)
    return requested


def load(page: Page, name: str, quote_class: str = "quote") -> tuple[list[Quote], str | None]:
    page.set_content((FIXTURES / name).read_text())
    return extract_quotes(page, quote_class)


def test_extract_quotes_reads_every_field_and_the_next_link(page: Page) -> None:
    quotes, next_href = load(page, "quotes_page1.html")
    assert len(quotes) == 10
    assert quotes[0].author == "Albert Einstein"
    assert quotes[0].tags == ["change", "deep-thoughts", "thinking", "world"]
    assert quotes[0].text.startswith("\u201cThe world as we have created it")
    assert next_href == "/page/2/"


def test_extract_quotes_last_page_has_no_next_link(page: Page) -> None:
    quotes, next_href = load(page, "quotes_page10.html")
    assert len(quotes) == 10
    assert next_href is None


def test_extract_quotes_with_wrong_selector_finds_nothing(page: Page) -> None:
    quotes, _ = load(page, "quotes_page1.html", "qoute")
    assert quotes == []


def test_extract_quotes_keeps_a_quote_missing_its_author(page: Page) -> None:
    page.set_content('<div class="quote"><span class="text">hi</span></div>')
    assert extract_quotes(page)[0] == [Quote("hi", "", [])]


def test_parse_trends_reads_title_traffic_and_date() -> None:
    trends = parse_trends((FIXTURES / "trends_gb.xml").read_text())
    assert trends
    assert trends[0].title == "rob cross"
    assert trends[0].approx_traffic == "200+"
    assert trends[0].published.startswith("Wed, 18 Nov 2026")
    assert all(t.title and t.approx_traffic and t.published for t in trends)


def test_scroll_reads_every_page_from_the_xhr_responses(fresh_page: Page) -> None:
    requested = serve_scroll(fresh_page)
    quotes = scroll_quotes(fresh_page, SCROLL_URL)
    assert len(quotes) == 100
    assert quotes[0] == Quote("q1-0", "A", ["t"])
    assert quotes[-1].text == "q10-9"
    assert requested == list(range(1, 11))


def test_scroll_stops_at_has_next_false(fresh_page: Page) -> None:
    requested = serve_scroll(fresh_page, last_page=3)
    assert len(scroll_quotes(fresh_page, SCROLL_URL)) == 30
    assert requested == [1, 2, 3]


def test_scroll_stall_returns_the_partial_rows_without_hanging(fresh_page: Page) -> None:
    serve_scroll(fresh_page, stop_after=3)
    started = time.monotonic()
    quotes = scroll_quotes(fresh_page, SCROLL_URL, stall_ms=200)
    assert len(quotes) == 30
    assert time.monotonic() - started < 10


def test_scroll_duplicate_responses_do_not_duplicate_rows(fresh_page: Page) -> None:
    requested = serve_scroll(fresh_page)
    quotes = scroll_quotes(fresh_page, SCROLL_URL + "?dup=1")
    assert len(requested) == 20
    assert len(quotes) == 100
    assert len({q.text for q in quotes}) == 100
