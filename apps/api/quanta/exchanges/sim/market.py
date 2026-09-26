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


def _hash_unit(index: int, seed: int) -> float:
    """A stable value in [-1, 1) for a grid point.

    SplitMix64's finaliser: cheap, and it decorrelates neighbouring
    indices well enough that the octaves do not line up into a pattern.
    """
    x = (index * 0x9E3779B97F4A7C15 + seed) & 0xFFFFFFFFFFFFFFFF
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 31
    return (x / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


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
        """A price path that behaves like a market, addressable in O(1).

        Two properties have to hold at once, and they pull against each
        other. The path must be *directly* computable at any timestamp, so
        that a request for one week of 2025 does not replay from an origin.
        And its returns must look like a market's: near-zero correlation
        from one bar to the next.

        An earlier version was a sum of sine waves with a small random
        nudge, which satisfied the first and badly failed the second. Its
        lag-2 return autocorrelation measured -0.87 where a real market
        sits near zero, and a Discover search over it duly "found" that a
        bar turning up predicted the next bar 96% of the time. That is a
        property of a sine wave, not of a market, and research run against
        it would have been measuring the generator.

        This is value noise summed over octaves instead: at each doubling
        of wavelength, a hash-derived value interpolated between grid
        points, with amplitude scaled by the square root of the wavelength.
        Summing those approximates Brownian motion, which is the cheapest
        honest model of a price — the increments are near-independent, so
        nothing in the path rewards predicting it.
        """
        seed = _seed(self.symbol)
        minutes = timestamp_ms / 60_000.0

        total = 0.0
        # 1 minute to about 11 days. Fewer octaves leaves visible steps at
        # the coarse end; more adds cost for movement no chart can show.
        for octave in range(15):
            wavelength = float(1 << octave)
            # Brownian scaling: variance grows with time, so amplitude
            # grows with its square root.
            total += self._octave(minutes / wavelength, seed + octave * 7919) * math.sqrt(
                wavelength
            )

        # Scaled so a day moves about 3-4%, which is BTC-like.
        return 1.0 + total * 0.0007

    @staticmethod
    def _octave(position: float, seed: int) -> float:
        """One layer of value noise: interpolated hashes at unit spacing."""
        index = math.floor(position)
        fraction = position - index
        left = _hash_unit(index, seed)
        right = _hash_unit(index + 1, seed)
        # Smoothstep, so the path has no corners where octaves meet.
        weight = fraction * fraction * (3.0 - 2.0 * fraction)
        return left + (right - left) * weight

    def bar(
        self,
        open_time: int,
        interval: Interval,
        *,
        closed: bool = True,
        now_ms: int | None = None,
    ) -> Bar:
        """Build the bar opening at ``open_time``.

        A forming bar (``closed=False`` with ``now_ms`` given) only covers
        the path so far: its close is the price *now*, and its high and low
        come from the elapsed part of the bar. Running it to the bar's future
        close time instead would leave the live candle frozen, which is
        exactly the behaviour a chart must not have.
        """
        anchor = self.anchor
        step = interval.milliseconds

        end_time = open_time + step
        if not closed and now_ms is not None:
            end_time = max(open_time, min(now_ms, open_time + step))

        open_factor = self._price_at(open_time)
        close_factor = self._price_at(end_time)
        # Sample inside the elapsed span so the wick reflects the path.
        elapsed = end_time - open_time
        mid_factors = [self._price_at(open_time + elapsed * k // 4) for k in (1, 2, 3)]

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
            bars.append(self.bar(open_time, interval, closed=not is_forming, now_ms=now_ms))
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
