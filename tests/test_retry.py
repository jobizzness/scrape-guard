import httpx
import pytest

from scrape_guard.retry import fetch_text, retry


def client_with(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_succeeds_on_the_third_attempt() -> None:
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200 if len(calls) == 3 else 503, text="ok")

    sleeps: list[float] = []
    assert fetch_text(client_with(httpx.MockTransport(flaky)), "https://x.test", sleeps.append) == "ok"
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_raises_after_the_maximum_attempts() -> None:
    calls = []

    def always_failing(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_text(client_with(httpx.MockTransport(always_failing)), "https://x.test", lambda _: None)
    assert len(calls) == 4


def test_backoff_is_bounded_by_the_cap() -> None:
    sleeps: list[float] = []

    def boom() -> None:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        retry(boom, attempts=6, base=1.0, cap=2.0, sleep=sleeps.append)
    assert len(sleeps) == 5
    assert all(0 <= s <= 2.0 for s in sleeps)


def test_unexpected_errors_are_not_retried() -> None:
    calls = []

    def bug() -> None:
        calls.append(1)
        raise ValueError

    with pytest.raises(ValueError):
        retry(bug, sleep=lambda _: None)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 403, 404])
def test_client_errors_raise_immediately(status: int) -> None:
    calls = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_text(client_with(httpx.MockTransport(refuse)), "https://x.test", lambda _: None)
    assert len(calls) == 1


def test_too_many_requests_is_retried() -> None:
    calls = []

    def limited(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200 if len(calls) == 2 else 429, text="ok")

    assert fetch_text(client_with(httpx.MockTransport(limited)), "https://x.test", lambda _: None) == "ok"
