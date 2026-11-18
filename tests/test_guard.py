from pathlib import Path

from scrape_guard.guard import Guard, GuardConfig
from scrape_guard.models import Kind, Quote, Row


class StubSource:
    name = "stub"
    required = ("text", "author")

    def fetch(self) -> list[Row]:
        return []


def quotes(count: int, author: str = "A", tags: tuple[str, ...] = ("t",)) -> list[Row]:
    return [Quote(f"q{i}", author, list(tags)) for i in range(count)]


def kinds(guard: Guard, rows: list[Row]) -> list[Kind]:
    return [alert.kind for alert in guard.check(StubSource(), rows)]


def seeded(runs: int = 3, count: int = 100) -> Guard:
    guard = Guard()
    for _ in range(runs):
        assert kinds(guard, quotes(count)) == []
    return guard


def test_first_runs_do_not_alert_on_count() -> None:
    guard = Guard()
    assert kinds(guard, quotes(100)) == []
    assert kinds(guard, quotes(10)) == []


def test_zero_rows() -> None:
    assert kinds(seeded(), []) == [Kind.ZERO_ROWS]


def test_zero_rows_alerts_even_with_no_history() -> None:
    assert kinds(Guard(), []) == [Kind.ZERO_ROWS]


def test_count_drop_below_half_the_median() -> None:
    assert kinds(seeded(), quotes(49)) == [Kind.COUNT_DROP]


def test_count_at_the_threshold_is_fine() -> None:
    assert kinds(seeded(), quotes(50)) == []


def test_median_ignores_one_outlier_run() -> None:
    guard = seeded(runs=4)
    assert kinds(guard, quotes(1)) == [Kind.COUNT_DROP]
    assert kinds(guard, quotes(100)) == []


def test_ratio_and_window_are_configurable() -> None:
    guard = Guard(config=GuardConfig(min_ratio=0.9, min_history=1))
    assert kinds(guard, quotes(100)) == []
    assert kinds(guard, quotes(85)) == [Kind.COUNT_DROP]


def test_required_field_empty_rate() -> None:
    guard = seeded()
    rows = quotes(70) + quotes(30, author="  ")
    assert kinds(guard, rows) == [Kind.EMPTY_FIELD]


def test_empty_rate_at_the_limit_is_fine() -> None:
    rows = quotes(80) + quotes(20, author="")
    assert kinds(seeded(), rows) == []


def test_optional_field_going_empty_is_drift_not_an_empty_alert() -> None:
    assert kinds(seeded(), quotes(100, tags=())) == [Kind.SCHEMA_DRIFT]


def test_schema_drift_when_a_field_disappears() -> None:
    alerts = seeded().check(StubSource(), quotes(100, tags=()))
    assert [a.kind for a in alerts] == [Kind.SCHEMA_DRIFT]
    assert "lost ['tags']" in alerts[0].message


def test_schema_drift_when_a_field_appears() -> None:
    guard = Guard()
    assert kinds(guard, quotes(10, tags=())) == []
    alerts = guard.check(StubSource(), quotes(10))
    assert [a.kind for a in alerts] == [Kind.SCHEMA_DRIFT]
    assert "gained ['tags']" in alerts[0].message


def test_history_is_kept_per_source() -> None:
    guard = seeded()

    class Other(StubSource):
        name = "other"

    assert [a.kind for a in guard.check(Other(), quotes(1))] == []


def test_history_persists_in_the_database(tmp_path: Path) -> None:
    database = tmp_path / "runs.db"
    for _ in range(3):
        Guard(database).check(StubSource(), quotes(100))
    assert kinds(Guard(database), quotes(10)) == [Kind.COUNT_DROP]


def test_zero_row_runs_stay_out_of_the_baseline() -> None:
    guard = Guard(config=GuardConfig(min_history=1))
    assert kinds(guard, quotes(100)) == []
    for _ in range(3):
        assert kinds(guard, []) == [Kind.ZERO_ROWS]
    assert kinds(guard, quotes(40)) == [Kind.COUNT_DROP]
