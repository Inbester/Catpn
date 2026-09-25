"""Download a historical range into Timescale.

SPEC §6 is explicit that history is stored once, server-side, and never
queried live per user: the venue allows ten requests a second per IP, which
per-user history downloads would exhaust immediately. Boot only warms a
recent window, so the deep history a forward test or a walk-forward needs
is loaded by an operator running this:

    python -m quanta.tools.backfill BTCUSDT 1h --start 2025-03-01 --end 2026-05-01

Dates are parsed as UTC. A bare date means midnight; a full timestamp is
accepted too. The range is inclusive of ``--start`` and exclusive of
``--end``, so consecutive months do not overlap by one bar.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from quanta.core.config import get_settings
from quanta.db.session import dispose_engine, get_session_factory
from quanta.exchanges.base import Interval
from quanta.exchanges.bitunix import BitunixAdapter
from quanta.services.market_data import MarketDataService


def parse_moment(raw: str) -> int:
    """Turn a UTC date or timestamp into epoch milliseconds."""
    text = raw.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:  # argparse renders this as a usage error
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not a date (2025-03-21) or timestamp (2025-03-21T00:00:00)"
        ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m quanta.tools.backfill", description=__doc__)
    parser.add_argument("symbol", help="contract symbol, e.g. BTCUSDT")
    parser.add_argument("interval", help=f"one of {', '.join(i.value for i in Interval)}")
    parser.add_argument("--start", required=True, type=parse_moment, help="UTC date or timestamp")
    parser.add_argument("--end", required=True, type=parse_moment, help="UTC date or timestamp")
    parser.add_argument(
        "--price-type",
        default="LAST",
        choices=["LAST", "MARK"],
        help="LAST for traded price, MARK for the price liquidations use",
    )
    parser.add_argument(
        "--fill-gaps",
        action="store_true",
        help="after downloading, re-request any stretch the venue skipped",
    )
    parser.add_argument(
        "--funding",
        action="store_true",
        help="also store the 8-hourly funding settlements over the same range",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    if args.end <= args.start:
        raise SystemExit("--end must be after --start")

    settings = get_settings()
    adapter = BitunixAdapter(rest_url=settings.exchange_rest_url, ws_url=settings.exchange_ws_url)
    service = MarketDataService(adapter, get_session_factory(), None)
    interval = Interval(args.interval)

    try:
        written = await service.backfill(
            args.symbol.upper(),
            interval,
            start=args.start,
            end=args.end,
            price_type=args.price_type,
        )
        if args.fill_gaps:
            written += await service.fill_gaps(
                args.symbol.upper(), interval, price_type=args.price_type
            )
        if args.funding:
            settlements = await service.backfill_funding(
                args.symbol.upper(), start=args.start, end=args.end
            )
            print(f"{settlements} funding settlements stored")
    finally:
        await adapter.close()
        await dispose_engine()

    return written


def main() -> None:
    args = build_parser().parse_args()
    written = asyncio.run(run(args))
    print(f"{written} bars stored")


if __name__ == "__main__":
    main()
