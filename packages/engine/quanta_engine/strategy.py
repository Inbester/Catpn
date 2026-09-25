"""Strategy definitions and their content hashes.

SPEC §4: a strategy version is identified by a content hash of its AST plus
its parameters. That hash is what a Setup locks (SPEC §0), what a forward
test freezes, and what an alert message reports — so it has to change when
and only when the strategy's *meaning* changes.

Formatting, comments and whitespace therefore do not affect it: the hash is
taken over the canonical rendering of the parsed tree, not the source text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from quanta_engine.dsl.errors import ParseError
from quanta_engine.dsl.evaluator import FUNCTIONS
from quanta_engine.dsl.nodes import Node, functions, identifiers
from quanta_engine.dsl.parser import parse

# Bar columns every strategy can read.
BAR_SERIES = ("open", "high", "low", "close", "volume", "hlc3", "ohlc4", "hl2")


class ExitReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    BREAK_EVEN = "break_even"
    OPPOSITE_SIGNAL = "opposite_signal"
    TIME_EXIT = "time_exit"
    LIQUIDATION = "liquidation"
    END_OF_DATA = "end_of_data"


class MarginMode(StrEnum):
    ISOLATED = "isolated"
    CROSS = "cross"


@dataclass(frozen=True, slots=True)
class ExitRules:
    """When a position closes.

    SPEC §3.2: the first rule hit closes the position. Sizes are expressed
    in ATR multiples or R-multiples rather than absolute prices so a rule
    means the same thing across symbols and volatility regimes.
    """

    # Stop loss at N x ATR below entry (long) or above (short).
    atr_stop_multiple: float | None = None
    atr_length: int = 14
    # Take profit at N x the stop distance (the "R" in R-multiple).
    take_profit_r: float | None = None
    # Move the stop to entry once price has run this many R in favour.
    break_even_at_r: float | None = None
    # Trail the stop by N x ATR once it is in profit.
    trailing_atr_multiple: float | None = None
    # Close when the opposite entry condition fires.
    exit_on_opposite: bool = True
    # Close after this many bars regardless.
    time_exit_bars: int | None = None

    def __post_init__(self) -> None:
        if self.atr_stop_multiple is not None and self.atr_stop_multiple <= 0:
            raise ValueError("atr_stop_multiple must be positive")
        if self.take_profit_r is not None and self.take_profit_r <= 0:
            raise ValueError("take_profit_r must be positive")
        if self.take_profit_r is not None and self.atr_stop_multiple is None:
            # R is defined by the stop distance; without a stop there is no R.
            raise ValueError("take_profit_r requires atr_stop_multiple")
        if self.break_even_at_r is not None and self.atr_stop_multiple is None:
            raise ValueError("break_even_at_r requires atr_stop_multiple")
        if self.atr_length < 1:
            raise ValueError("atr_length must be at least 1")
        if self.time_exit_bars is not None and self.time_exit_bars < 1:
            raise ValueError("time_exit_bars must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "atr_stop_multiple": self.atr_stop_multiple,
            "atr_length": self.atr_length,
            "take_profit_r": self.take_profit_r,
            "break_even_at_r": self.break_even_at_r,
            "trailing_atr_multiple": self.trailing_atr_multiple,
            "exit_on_opposite": self.exit_on_opposite,
            "time_exit_bars": self.time_exit_bars,
        }


@dataclass(frozen=True, slots=True)
class Strategy:
    """A named strategy: entry conditions, exits and parameters."""

    name: str
    long_entry: str | None = None
    short_entry: str | None = None
    exits: ExitRules = field(default_factory=ExitRules)
    params: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.long_entry and not self.short_entry:
            raise ValueError("A strategy needs at least one entry condition.")
        # Parse eagerly so an invalid strategy cannot be stored or hashed.
        self.compiled_long()
        self.compiled_short()

    def compiled_long(self) -> Node | None:
        return parse(self.long_entry) if self.long_entry else None

    def compiled_short(self) -> Node | None:
        return parse(self.short_entry) if self.short_entry else None

    # --- validation -----------------------------------------------------

    def unknown_names(self) -> set[str]:
        """Identifiers the strategy reads that nothing will provide."""
        known = set(BAR_SERIES) | set(self.params)
        used: set[str] = set()
        for node in (self.compiled_long(), self.compiled_short()):
            if node is not None:
                used |= identifiers(node)
        return used - known

    def unknown_functions(self) -> set[str]:
        used: set[str] = set()
        for node in (self.compiled_long(), self.compiled_short()):
            if node is not None:
                used |= functions(node)
        return used - set(FUNCTIONS)

    def validate(self) -> None:
        """Raise if the strategy references anything that does not exist."""
        unknown = self.unknown_names()
        if unknown:
            names = ", ".join(sorted(unknown))
            available = ", ".join(sorted(set(BAR_SERIES) | set(self.params)))
            raise ParseError(f"Unknown name(s): {names}. Available: {available}.")

        missing = self.unknown_functions()
        if missing:
            names = ", ".join(sorted(missing))
            raise ParseError(f"Unknown function(s): {names}.")

    # --- versioning -----------------------------------------------------

    def canonical(self) -> dict[str, Any]:
        """The content the version hash is taken over.

        Built from the parsed trees, so reformatting the source or adding a
        comment leaves the version alone — but changing a number or an
        operator does not.
        """
        long_node = self.compiled_long()
        short_node = self.compiled_short()
        return {
            "long": str(long_node) if long_node else None,
            "short": str(short_node) if short_node else None,
            "exits": self.exits.to_dict(),
            # Sorted and float-normalised so key order and 20 vs 20.0 do not
            # produce different versions of the same strategy.
            "params": {k: float(v) for k, v in sorted(self.params.items())},
        }

    def version_hash(self) -> str:
        payload = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def short_version(self) -> str:
        """The first 12 hex characters, for display."""
        return self.version_hash()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "long_entry": self.long_entry,
            "short_entry": self.short_entry,
            "exits": self.exits.to_dict(),
            "params": dict(self.params),
            "version": self.version_hash(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Strategy:
        exits_data = dict(data.get("exits") or {})
        return cls(
            name=str(data.get("name", "Untitled")),
            long_entry=data.get("long_entry"),
            short_entry=data.get("short_entry"),
            exits=ExitRules(**exits_data),
            params={k: float(v) for k, v in (data.get("params") or {}).items()},
        )
