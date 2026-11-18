import argparse
from collections.abc import Sequence

from .guard import Guard
from .sinks import notify
from .sources import QuotesSource, ScrollSource, TrendsSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrape-guard")
    parser.add_argument("--db", default="scrape_guard.db")
    sources = parser.add_subparsers(dest="command", required=True).add_parser("run").add_subparsers(required=True)
    quotes = sources.add_parser("quotes")
    quotes.add_argument("--quote-class", default="quote")
    quotes.set_defaults(build=lambda args: QuotesSource(args.quote_class))
    sources.add_parser("scroll").set_defaults(build=lambda args: ScrollSource())
    trends = sources.add_parser("trends")
    trends.add_argument("--geo", default="US")
    trends.set_defaults(build=lambda args: TrendsSource(args.geo))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.build(args)
    rows = source.fetch()
    alerts = Guard(args.db).check(source, rows)
    print(f"{source.name}: {len(rows)} rows")
    notify(alerts)
    # A non-zero exit makes a silent scraper failure fail the cron or CI job.
    return 1 if alerts else 0
