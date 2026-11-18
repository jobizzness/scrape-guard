import pytest

from scrape_guard.models import Alert, Kind
from scrape_guard.sinks import notify

ALERT = Alert("quotes", Kind.ZERO_ROWS, "quotes returned 0 rows")


class FakePost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, json: dict[str, str], timeout: int) -> None:
        self.calls.append((url, json))


def test_slack_is_skipped_without_the_env_var(capsys: pytest.CaptureFixture[str]) -> None:
    post = FakePost()
    notify([ALERT], env={}, post=post)
    assert post.calls == []
    assert "quotes returned 0 rows" in capsys.readouterr().err


def test_slack_receives_the_alerts_when_configured() -> None:
    post = FakePost()
    notify([ALERT], env={"SLACK_WEBHOOK_URL": "https://hooks.test/x"}, post=post)
    assert post.calls == [("https://hooks.test/x", {"text": str(ALERT)})]


def test_slack_is_skipped_when_nothing_fired() -> None:
    post = FakePost()
    notify([], env={"SLACK_WEBHOOK_URL": "https://hooks.test/x"}, post=post)
    assert post.calls == []
