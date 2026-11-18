from pathlib import Path

import pytest

from scrape_guard import cli
from scrape_guard.models import Quote, Row


class FakeQuotes:
    name = "quotes"
    required = ("text", "author")
    count = 10

    def __init__(self, quote_class: str = "quote") -> None:
        pass

    def fetch(self) -> list[Row]:
        return [Quote(f"q{i}", "A", ["t"]) for i in range(FakeQuotes.count)]


@pytest.fixture(autouse=True)
def fake_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "QuotesSource", FakeQuotes)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    FakeQuotes.count = 10


def run(tmp_path: Path) -> int:
    return cli.main(["--db", str(tmp_path / "runs.db"), "run", "quotes"])


def test_exit_zero_when_nothing_fires(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path) == 0
    assert capsys.readouterr().out == "quotes: 10 rows\n"


def test_exit_one_when_an_alert_fires(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for _ in range(3):
        assert run(tmp_path) == 0
    FakeQuotes.count = 0
    assert run(tmp_path) == 1
    assert "zero_rows" in capsys.readouterr().err


def test_scroll_is_a_source() -> None:
    args = cli.build_parser().parse_args(["run", "scroll"])
    assert args.build(args).name == "scroll"
