# scrape-guard

## The problem

Scrapers rarely fail loudly. A site renames a class or changes an API, the job still exits green, and it quietly returns 0 rows, 40 instead of 100, or every author blank. Nobody notices until the numbers downstream are wrong.

## The solution

Every run is recorded in SQLite and compared with that source's recent history. A drop raises an alert and fails the job:

```
$ uv run scrape-guard run quotes --quote-class qoute
[quotes:zero_rows] quotes returned 0 rows
quotes: 0 rows
$ echo $?
1
```

The hardest source is an infinite-scroll page that renders nothing on the server. The browser scrolls, and the code reads the page's own API responses instead of scraping the DOM:

```python
page.on("response", lambda response: arrived.append(response) if is_api(response) else None)
retry(partial(open_page, page, url))
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
```

A stalled scroll returns the rows it has, and the guard catches the shortfall against a median that earlier outages can't drag down:

```python
counts = [c for c, _ in history if c > 0]
if len(counts) >= config.min_history:
    median = statistics.median(counts)
    if count < config.min_ratio * median:
```

```
[scroll:count_drop] scroll returned 40 rows, under 50% of the median 100 over the last 3 runs
```

## Code quality

- **Small:** 387 lines across six modules (366 without comments), each with one job. There is no framework, only `playwright`, `httpx` and the standard library.
- **One seam for sources:** a new source is one class.

  ```python
  class Source(Protocol):
      name: str
      required: tuple[str, ...]

      def fetch(self) -> Sequence[Row]: ...
  ```
- **Retries that know when to stop:** network errors, 5xx and 429 back off with jitter, and other 4xx responses fail at once.
- **Testable by design:** `sleep`, `post` and `env` are injected, and the browser tests serve fixtures through `page.route`. All 38 tests run with no network.
- **Strict:** `mypy --strict` and `ruff` are clean. Comments explain why, not what.

```
uv sync && uv run playwright install chromium
uv run pytest -q
uv run scrape-guard run scroll
```
