import json
import sqlite3
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Alert, Kind, Row, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    source TEXT NOT NULL,
    at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    fields TEXT NOT NULL,
    empty_rates TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class GuardConfig:
    min_ratio: float = 0.5
    window: int = 7
    min_history: int = 3
    max_empty_rate: float = 0.2


def is_blank(value: object) -> bool:
    return not value or (isinstance(value, str) and not value.strip())


# Share of rows where each field is blank: one pass over the rows.
def empty_rates(rows: Sequence[Row]) -> dict[str, float]:
    records = [asdict(row) for row in rows]
    if not records:
        return {}
    return {name: sum(is_blank(r[name]) for r in records) / len(records) for name in records[0]}


class Guard:
    def __init__(self, path: str | Path = ":memory:", config: GuardConfig = GuardConfig()) -> None:
        self.config = config
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)

    def check(self, source: Source, rows: Sequence[Row], now: datetime | None = None) -> list[Alert]:
        rates = empty_rates(rows)
        # Rows are fixed dataclasses, so a field "exists" only if some row has a value for it.
        fields = sorted(name for name, rate in rates.items() if rate < 1)
        # Compare before recording, so a run is never judged against itself.
        alerts = self._compare(source, len(rows), rates, fields)
        self.db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
            (source.name, (now or datetime.now(UTC)).isoformat(), len(rows), json.dumps(fields), json.dumps(rates)),
        )
        self.db.commit()
        return alerts

    def _history(self, name: str) -> list[tuple[int, list[str]]]:
        cursor = self.db.execute(
            "SELECT row_count, fields FROM runs WHERE source = ? ORDER BY rowid DESC LIMIT ?",
            (name, self.config.window),
        )
        return [(count, json.loads(fields)) for count, fields in cursor]

    def _compare(self, source: Source, count: int, rates: dict[str, float], fields: list[str]) -> list[Alert]:
        name, config = source.name, self.config
        history = self._history(name)
        # Zero rows says it all; the other checks would only add noise.
        if count == 0:
            return [Alert(name, Kind.ZERO_ROWS, f"{name} returned 0 rows")]
        alerts = []
        # Median, not mean, and outages excluded, so a few bad runs can't lower the bar.
        counts = [c for c, _ in history if c > 0]
        if len(counts) >= config.min_history:
            median = statistics.median(counts)
            if count < config.min_ratio * median:
                message = f"{name} returned {count} rows, under {config.min_ratio:.0%} of the median {median:g} over the last {len(counts)} runs"
                alerts.append(Alert(name, Kind.COUNT_DROP, message))
        for field in source.required:
            if rates[field] > config.max_empty_rate:
                message = f"{name}: '{field}' is empty in {rates[field]:.0%} of rows, limit {config.max_empty_rate:.0%}"
                alerts.append(Alert(name, Kind.EMPTY_FIELD, message))
        # Drift is measured against the last healthy run only.
        if history and history[0][0] > 0 and set(history[0][1]) != set(fields):
            lost = sorted(set(history[0][1]) - set(fields))
            gained = sorted(set(fields) - set(history[0][1]))
            message = f"{name}: fields changed since the previous run, lost {lost or 'none'}, gained {gained or 'none'}"
            alerts.append(Alert(name, Kind.SCHEMA_DRIFT, message))
        return alerts
