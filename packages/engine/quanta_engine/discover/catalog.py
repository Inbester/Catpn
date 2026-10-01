"""The indicators a Discover search can be built from (SPEC §3.2).

A user picks indicators, sets their parameters, and may feed one into
another — an EMA of RSI, an SMA of volume. This module turns those choices
into the series the enumerator works on, each placed on a scale.

The scale is what makes combining safe. Only series on one scale are
compared to each other, so an indicator's scale has to be right or the
search tests nonsense:

- A smoothing indicator (EMA, SMA, Bollinger) lives on its **input's**
  scale. EMA 9 of RSI 14 is an RSI-scaled line, so "RSI crosses its EMA"
  is found, and "EMA of RSI above EMA 50 of price" never is.
- An oscillator lives on **its own** scale whatever it is fed: RSI of
  volume is still 0-100.

Choices arrive as data from a request, so everything here is validated:
an unknown indicator, a parameter outside its range, or an input that does
not exist yet is a `CatalogError` with a sentence the user can act on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from quanta_engine.discover.primitives import ScaleName, Series, Source
from quanta_engine.series import atr, bollinger, ema, macd_lines, rsi, sma

Array = NDArray[np.float64]

PRICE_KEY = "close"
PRICE_SOURCE = Source(key="price", label="Price", is_price=True)

# One request may hold this many indicators. Each adds series, and the rule
# count grows roughly with the cube of the series count; the plan step
# reports the size before anything runs, but a cap keeps planning itself
# cheap.
MAX_INDICATORS = 8

# A scale value of None means "the scale of whatever this is applied to".
INHERIT: None = None

_KEY = re.compile(r"^[a-z][a-z0-9]{0,15}$")


class CatalogError(ValueError):
    """A choice the catalog cannot honour. The message is shown to the user."""


class OHLCV(Protocol):
    @property
    def high(self) -> Array: ...
    @property
    def low(self) -> Array: ...
    @property
    def close(self) -> Array: ...
    @property
    def volume(self) -> Array: ...


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    label: str
    default: float
    minimum: float
    maximum: float
    integer: bool = True


@dataclass(frozen=True, slots=True)
class Output:
    key: str
    # Appended to the indicator's label when it has more than one line.
    label: str
    scale: ScaleName | None


Compute = Callable[[OHLCV, Array | None, Mapping[str, float]], dict[str, Array]]


@dataclass(frozen=True, slots=True)
class Indicator:
    id: str
    name: str
    params: tuple[Param, ...]
    outputs: tuple[Output, ...]
    compute: Compute
    # True: works on one series (close by default, or another indicator's
    # line). False: reads the bars themselves — high, low, volume.
    takes_input: bool = True
    description: str = ""

    def label(self, params: Mapping[str, float]) -> str:
        if not self.params:
            return self.name
        values = "/".join(_fmt(params[p.name]) for p in self.params)
        return f"{self.name} {values}"


@dataclass(frozen=True, slots=True)
class Choice:
    """One indicator the user added."""

    # Stable within a request, chosen by the client ("i1", "i2"…), so an
    # input reference survives a parameter change.
    key: str
    id: str
    params: Mapping[str, float] = field(default_factory=dict)
    # PRICE_KEY, or "<key>.<output>" of an indicator listed before this one.
    input: str = PRICE_KEY


def _fmt(value: float) -> str:
    return f"{value:g}"


def _dense(values: Array, fn: Callable[[Array], Array]) -> Array:
    """Apply ``fn`` from the first finite value on.

    An indicator fed another indicator receives leading NaNs for the
    input's warm-up. The recursive averages seed from their first window,
    so a NaN there would poison every value after it.
    """
    out = np.full(values.shape, np.nan, dtype=np.float64)
    finite = np.flatnonzero(np.isfinite(values))
    if finite.size == 0:
        return out
    start = int(finite[0])
    out[start:] = fn(values[start:])
    return out


def _dense_many(values: Array, fn: Callable[[Array], tuple[Array, ...]]) -> tuple[Array, ...]:
    """`_dense` for a formula that returns several lines at once."""
    finite = np.flatnonzero(np.isfinite(values))
    if finite.size == 0:
        empty = np.full(values.shape, np.nan, dtype=np.float64)
        return tuple(empty.copy() for _ in fn(values[:0]))
    start = int(finite[0])
    lines = []
    for computed in fn(values[start:]):
        out = np.full(values.shape, np.nan, dtype=np.float64)
        out[start:] = computed
        lines.append(out)
    return tuple(lines)


def _source(values: Array | None) -> Array:
    if values is None:  # pragma: no cover - guarded by takes_input
        raise CatalogError("This indicator needs an input series.")
    return values


def _int(params: Mapping[str, float], name: str) -> int:
    return int(params[name])


# --- formulas not in quanta_engine.series --------------------------------


def stochastic(
    high: Array, low: Array, close: Array, length: int, smooth: int, signal: int
) -> tuple[Array, Array]:
    """Slow stochastic: %K smoothed by ``smooth``, %D its SMA."""
    out = np.full(close.shape, np.nan, dtype=np.float64)
    if close.size >= length:
        top = sliding_window_view(high, length).max(axis=1)
        bottom = sliding_window_view(low, length).min(axis=1)
        width = top - bottom
        with np.errstate(divide="ignore", invalid="ignore"):
            raw = np.where(width > 0, 100.0 * (close[length - 1 :] - bottom) / width, 50.0)
        out[length - 1 :] = raw
    k = _dense(out, lambda v: sma(v, smooth))
    d = _dense(k, lambda v: sma(v, signal))
    return k, d


def cci(high: Array, low: Array, close: Array, length: int) -> Array:
    """Commodity channel index with Lambert's 0.015 constant."""
    typical = (high + low + close) / 3.0
    out = np.full(close.shape, np.nan, dtype=np.float64)
    if close.size < length:
        return out
    windows = sliding_window_view(typical, length)
    mean = windows.mean(axis=1)
    deviation = np.abs(windows - mean[:, None]).mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(deviation > 0, (typical[length - 1 :] - mean) / (0.015 * deviation), 0.0)
    out[length - 1 :] = value
    return out


def roc(values: Array, length: int) -> Array:
    """Rate of change in percent over ``length`` bars."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size <= length:
        return out
    previous = values[:-length]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[length:] = np.where(previous != 0, 100.0 * (values[length:] / previous - 1.0), np.nan)
    return out


# --- the catalog ------------------------------------------------------------


def _length(default: float, maximum: float = 500) -> Param:
    return Param("length", "Length", default, 2, maximum)


CATALOG: dict[str, Indicator] = {
    item.id: item
    for item in (
        Indicator(
            id="ema",
            name="EMA",
            params=(_length(20),),
            outputs=(Output("ema", "", INHERIT),),
            compute=lambda bars, x, p: {
                "ema": _dense(_source(x), lambda v: ema(v, _int(p, "length")))
            },
            description="Exponential moving average.",
        ),
        Indicator(
            id="sma",
            name="SMA",
            params=(_length(50),),
            outputs=(Output("sma", "", INHERIT),),
            compute=lambda bars, x, p: {
                "sma": _dense(_source(x), lambda v: sma(v, _int(p, "length")))
            },
            description="Simple moving average.",
        ),
        Indicator(
            id="bb",
            name="Bollinger",
            params=(
                _length(20),
                Param("multiplier", "Width (std devs)", 2.0, 0.5, 5.0, integer=False),
            ),
            outputs=(
                Output("upper", "upper", INHERIT),
                Output("basis", "basis", INHERIT),
                Output("lower", "lower", INHERIT),
            ),
            compute=lambda bars, x, p: _bollinger(_source(x), p),
            description="Moving average with bands a number of standard deviations away.",
        ),
        Indicator(
            id="rsi",
            name="RSI",
            params=(_length(14, 100),),
            outputs=(Output("rsi", "", "bounded_100"),),
            compute=lambda bars, x, p: {
                "rsi": _dense(_source(x), lambda v: rsi(v, _int(p, "length")))
            },
            description="Relative strength index, 0-100.",
        ),
        Indicator(
            id="macd",
            name="MACD",
            params=(
                Param("fast", "Fast", 12, 2, 200),
                Param("slow", "Slow", 26, 3, 400),
                Param("signal", "Signal", 9, 2, 100),
            ),
            outputs=(
                Output("macd", "line", "centered_0"),
                Output("signal", "signal", "centered_0"),
            ),
            compute=lambda bars, x, p: _macd(_source(x), p),
            description="Difference of two EMAs, with its own EMA as a signal line.",
        ),
        Indicator(
            id="roc",
            name="ROC",
            params=(_length(10, 200),),
            outputs=(Output("roc", "", "centered_0"),),
            compute=lambda bars, x, p: {
                "roc": _dense(_source(x), lambda v: roc(v, _int(p, "length")))
            },
            description="Rate of change: percent move over the last N bars.",
        ),
        Indicator(
            id="stoch",
            name="Stochastic",
            params=(
                Param("length", "%K length", 14, 2, 200),
                Param("smooth", "%K smoothing", 3, 1, 20),
                Param("signal", "%D", 3, 1, 20),
            ),
            outputs=(Output("k", "%K", "bounded_100"), Output("d", "%D", "bounded_100")),
            compute=lambda bars, x, p: _stochastic(bars, p),
            takes_input=False,
            description="Where the close sits in the recent high-low range, 0-100.",
        ),
        Indicator(
            id="cci",
            name="CCI",
            params=(_length(20, 200),),
            outputs=(Output("cci", "", "centered_100"),),
            compute=lambda bars, x, p: {
                "cci": cci(bars.high, bars.low, bars.close, _int(p, "length"))
            },
            takes_input=False,
            description="Commodity channel index; ±100 are its usual extremes.",
        ),
        Indicator(
            id="atr",
            name="ATR",
            params=(_length(14, 200),),
            outputs=(Output("atr", "", "volatility"),),
            compute=lambda bars, x, p: {
                "atr": atr(bars.high, bars.low, bars.close, _int(p, "length"))
            },
            takes_input=False,
            description="Average true range: how far price typically moves per bar.",
        ),
        Indicator(
            id="volume",
            name="Volume",
            params=(),
            outputs=(Output("volume", "", "volume"),),
            compute=lambda bars, x, p: {"volume": np.asarray(bars.volume, dtype=np.float64)},
            takes_input=False,
            description="Traded volume per bar. Feed it to an SMA to find volume spikes.",
        ),
    )
}


def _bollinger(values: Array, p: Mapping[str, float]) -> dict[str, Array]:
    length, width = _int(p, "length"), float(p["multiplier"])
    basis, upper, lower = _dense_many(values, lambda v: bollinger(v, length, width))
    return {"upper": upper, "basis": basis, "lower": lower}


def _macd(values: Array, p: Mapping[str, float]) -> dict[str, Array]:
    fast, slow, signal = _int(p, "fast"), _int(p, "slow"), _int(p, "signal")
    line, sig, _ = _dense_many(values, lambda v: macd_lines(v, fast, slow, signal))
    return {"macd": line, "signal": sig}


def _stochastic(bars: OHLCV, p: Mapping[str, float]) -> dict[str, Array]:
    k, d = stochastic(
        np.asarray(bars.high, dtype=np.float64),
        np.asarray(bars.low, dtype=np.float64),
        np.asarray(bars.close, dtype=np.float64),
        _int(p, "length"),
        _int(p, "smooth"),
        _int(p, "signal"),
    )
    return {"k": k, "d": d}


# --- turning choices into series --------------------------------------------


@dataclass(frozen=True, slots=True)
class Built:
    """What a list of choices becomes: the series, their data, and labels."""

    series: list[Series]
    data: dict[str, Array]
    # Instance key -> its display label ("EMA 9 of RSI 14").
    labels: dict[str, str]


def resolve_params(indicator: Indicator, given: Mapping[str, float]) -> dict[str, float]:
    """Defaults filled in, every value checked against its range."""
    unknown = set(given) - {p.name for p in indicator.params}
    if unknown:
        raise CatalogError(f"{indicator.name} has no setting called {sorted(unknown)[0]!r}.")
    resolved: dict[str, float] = {}
    for param in indicator.params:
        raw = given.get(param.name, param.default)
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise CatalogError(f"{indicator.name} {param.label} must be a number.") from exc
        if not np.isfinite(value) or not param.minimum <= value <= param.maximum:
            raise CatalogError(
                f"{indicator.name} {param.label} must be between "
                f"{_fmt(param.minimum)} and {_fmt(param.maximum)}."
            )
        if param.integer and value != int(value):
            raise CatalogError(f"{indicator.name} {param.label} must be a whole number.")
        resolved[param.name] = value
    if indicator.id == "macd" and resolved["fast"] >= resolved["slow"]:
        raise CatalogError("MACD Fast must be shorter than Slow.")
    return resolved


def build(choices: list[Choice], bars: OHLCV) -> Built:
    """The series a search runs on: price first, then each choice in order.

    Price is always present: divergence is defined against it, and a
    search with no price has no returns to explain.
    """
    if len(choices) > MAX_INDICATORS:
        raise CatalogError(f"A search can use at most {MAX_INDICATORS} indicators.")

    close = np.asarray(bars.close, dtype=np.float64)
    series: list[Series] = [Series(PRICE_KEY, "Price", PRICE_SOURCE, "price")]
    data: dict[str, Array] = {PRICE_KEY: close}
    scales: dict[str, ScaleName] = {PRICE_KEY: "price"}
    line_labels: dict[str, str] = {PRICE_KEY: "Price"}
    labels: dict[str, str] = {}

    for choice in choices:
        if not _KEY.match(choice.key):
            raise CatalogError(f"{choice.key!r} is not a usable indicator key.")
        if choice.key in labels:
            raise CatalogError(f"Indicator key {choice.key!r} is used twice.")
        indicator = CATALOG.get(choice.id)
        if indicator is None:
            raise CatalogError(f"There is no indicator called {choice.id!r}.")
        params = resolve_params(indicator, choice.params)

        label = indicator.label(params)
        input_values: Array | None = None
        input_scale: ScaleName = "price"
        if indicator.takes_input:
            if choice.input not in data:
                raise CatalogError(
                    f"{label} is applied to {choice.input!r}, which is not price or an "
                    "indicator listed above it."
                )
            input_values = data[choice.input]
            input_scale = scales[choice.input]
            if choice.input != PRICE_KEY:
                label = f"{label} of {line_labels[choice.input]}"
        elif choice.input != PRICE_KEY:
            raise CatalogError(f"{indicator.name} reads the bars directly and takes no input.")

        computed = indicator.compute(bars, input_values, params)
        source = Source(key=choice.key, label=label)
        labels[choice.key] = label
        for output in indicator.outputs:
            line_key = f"{choice.key}.{output.key}"
            line_label = label if len(indicator.outputs) == 1 else f"{label} {output.label}"
            scale: ScaleName = output.scale if output.scale is not None else input_scale
            series.append(Series(line_key, line_label, source, scale))
            data[line_key] = computed[output.key]
            scales[line_key] = scale
            line_labels[line_key] = line_label

    return Built(series=series, data=data, labels=labels)


def describe() -> list[dict[str, object]]:
    """The catalog as data, for the picker."""
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "takes_input": item.takes_input,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "default": p.default,
                    "min": p.minimum,
                    "max": p.maximum,
                    "integer": p.integer,
                }
                for p in item.params
            ],
            "outputs": [{"key": o.key, "label": o.label} for o in item.outputs],
        }
        for item in CATALOG.values()
    ]
