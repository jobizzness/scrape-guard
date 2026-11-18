import random
import time
from collections.abc import Callable

import httpx
from playwright.sync_api import Error as PlaywrightError

TRANSIENT = (httpx.HTTPError, PlaywrightError)


# A 4xx (other than 429 rate limiting) will fail the same way every time, so don't retry it.
def is_permanent(error: Exception) -> bool:
    if not isinstance(error, httpx.HTTPStatusError):
        return False
    status = error.response.status_code
    return status < 500 and status != 429


def retry[T](
    call: Callable[[], T],
    attempts: int = 4,
    base: float = 0.5,
    cap: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(attempts - 1):
        try:
            return call()
        except TRANSIENT as error:
            if is_permanent(error):
                raise
            # Full jitter: a random wait up to the exponential cap, so parallel jobs don't retry in lockstep.
            sleep(random.uniform(0, min(cap, base * 2**attempt)))
    # The last attempt runs outside the try, so its error reaches the caller unchanged.
    return call()


def fetch_text(client: httpx.Client, url: str, sleep: Callable[[float], None] = time.sleep) -> str:
    def attempt() -> str:
        response = client.get(url)
        response.raise_for_status()
        return response.text

    return retry(attempt, sleep=sleep)
