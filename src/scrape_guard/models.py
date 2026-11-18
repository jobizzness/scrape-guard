from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class Quote:
    text: str
    author: str
    tags: list[str]


@dataclass(frozen=True)
class Trend:
    title: str
    approx_traffic: str
    published: str


Row = Quote | Trend


# Any class with these three members is a source; no base class or registration.
class Source(Protocol):
    name: str
    required: tuple[str, ...]

    def fetch(self) -> Sequence[Row]: ...


class Kind(StrEnum):
    ZERO_ROWS = "zero_rows"
    COUNT_DROP = "count_drop"
    EMPTY_FIELD = "empty_field"
    SCHEMA_DRIFT = "schema_drift"


@dataclass(frozen=True)
class Alert:
    source: str
    kind: Kind
    message: str

    def __str__(self) -> str:
        return f"[{self.source}:{self.kind}] {self.message}"
