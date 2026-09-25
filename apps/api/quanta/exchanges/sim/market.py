"""A deterministic synthetic market.

This is development scaffolding, not a model of anything. It exists because
the exchange is not always reachable (a restricted region per SPEC §9, a
locked-down CI network, or simply working offline), and the chart, the
backfill and the WebSocket fan-out all need bars to work on.

The series is generated from a seed, so the same symbol and timeframe give
byte-identical bars on every run — which is what makes it usable as test
data rather than just a demo.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from quanta.exchanges.base import Bar, Interval

# Anchor prices so BTC looks like BTC. Anything unlisted gets a price
# derived from its name, which keeps new symbols stable across restarts.
ANCHOR_PRICES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("64000"),
    "ETHUSDT": Decimal("3400"),
    "SOLUSDT": Decimal("148"),
    "BNBUSDT": Decimal("582"),
    "XRPUSDT": Decimal("0.587"),
    "DOGEUSDT": Decimal("0.1294"),
    "TONUSDT": Decimal("5.21"),
    "AVAXUSDT": Decimal("27.6"),
    "LINKUSDT": Decimal("13.48"),
    "ADAUSDT": Decimal("0.392"),
    "SUIUSDT": Decimal("1.084"),
    "ARBUSDT": Decimal("0.661"),
}

SIM_SYMBOLS: tuple[str, ...] = tuple(ANCHOR_PRICES)


def _seed(symbol: str) -> int:
    """A stable 32-bit seed for a symbol."""
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _quantize(value: Decimal, anchor: Decimal) -> Decimal:
    """Round to a sensible tick for the price's magnitude."""
    if anchor >= 1000:
        exponent = Decimal("0.1")
    elif anchor >= 10:
        exponent = Decimal("0.001")
    elif anchor >= 1:
        exponent = Decimal("0.0001")
    else:
        exponent = Decimal("0.00001")
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class SyntheticMarket:
    """Generates reproducible OHLCV for one symbol."""

    symbol: str

    @property
    def anchor(self) -> Decimal:
        known = ANCHOR_PRICES.get(self.symbol)
        if known is not None:
            return known
        # Unknown symbols land somewhere between 0.5 and 500.
        return Decimal(_seed(self.symbol) % 50_000) / Decimal(100) + Decimal("0.5")

    def _price_at(self, timestamp_ms: int) -> float:
        """A smooth price path: several sine waves plus a hash-based wobble.

        Deterministic in the timestamp, so any window can be generated
        directly without replaying from the beginning.
        """
        seed = _seed(self.symbol)
        t = timestamp_ms / 60_000.0  # minutes

        trend = math.sin((t + seed % 1000) / 5_000.0) * 0.08
        swing = math.sin((t + seed % 300) / 620.0) * 0.035
        ripple = math.sin((t + seed % 97) / 41.0) * 0.012

        # A per-minute pseudo-random nudge, stable for a given minute.
        bucket = int(t) ^ seed
        noise = ((bucket * 1_103_515_245 + 12_345) % 10_000) / 10_000.0 - 0.5
        return 1.0 + trend + swing + ripple + noise * 0.004

    def bar(self, open_time: int, interval: Interval, *, closed: bool = True) -> Bar:
        """Build the bar opening at ``open_time``."""
        anchor = self.anchor
        step = interval.milliseconds

        open_factor = self._price_at(open_time)
        close_factor = self._price_at(open_time + step)
        # Sample inside the bar so the wick reflects the path, not just ends.
        mid_factors = [self._price_at(open_time + step * k // 4) for k in (1, 2, 3)]

        open_price = Decimal(str(open_factor)) * anchor
        close_price = Decimal(str(close_factor)) * anchor
        samples = [open_price, close_price] + [Decimal(str(f)) * anchor for f in mid_factors]

        high = max(samples)
        low = min(samples)

        # Volume rises with the bar's range, which is roughly how real
        # markets behave and makes the volume pane look plausible.
        span = float(high - low) / float(anchor) if anchor else 0.0
        base_volume = 180 + span * 90_000 + (abs(hash((self.symbol, open_time))) % 220)

        return Bar(
            open_time=open_time,
            open=_quantize(open_price, anchor),
            high=_quantize(high, anchor),
            low=_quantize(low, anchor),
            close=_quantize(close_price, anchor),
            volume=Decimal(str(round(base_volume, 3))),
            quote_volume=_quantize(
                Decimal(str(round(base_volume, 3))) * close_price, Decimal("1000")
            ),
            closed=closed,
        )

    def bars(
        self, *, start: int, end: int, interval: Interval, now_ms: int | None = None
    ) -> list[Bar]:
        """Every bar whose open time falls in ``[start, end)``.

        The bar containing ``now_ms`` is returned with ``closed=False``.
        """
        step = interval.milliseconds
        first = (start // step) * step
        bars: list[Bar] = []
        open_time = first

        while open_time < end:
            is_forming = now_ms is not None and open_time <= now_ms < open_time + step
            bars.append(self.bar(open_time, interval, closed=not is_forming))
            open_time += step

        return bars

    def drift_at(self, timestamp_ms: int) -> float:
        """Signed deviation from the anchor at a point in time.

        Used by the simulator to derive a funding rate that flips sign the
        way a real one does.
        """
        return self._price_at(timestamp_ms) - 1.0

    def price_now(self, now_ms: int) -> Decimal:
        return _quantize(Decimal(str(self._price_at(now_ms))) * self.anchor, self.anchor)
