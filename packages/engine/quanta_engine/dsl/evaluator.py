"""Evaluate a parsed strategy expression over a bar series.

The sandbox (SPEC §5) is structural, not a filter: the evaluator can only
reach the series in its context and the functions in :data:`FUNCTIONS`.
There is no name lookup into Python, no attribute access, no imports and no
way to construct a call the parser did not produce.

On top of that come resource limits — node count, bar count and wall-clock
time — so a strategy cannot occupy a worker indefinitely.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from quanta_engine import series as ta
from quanta_engine.dsl.errors import EvaluationError, LimitExceededError
from quanta_engine.dsl.nodes import (
    Binary,
    Boolean,
    Call,
    Identifier,
    Node,
    Number,
    Unary,
)

Array = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
Value = Array | BoolArray | float | bool

# Default limits. The job runner can tighten them per user (SPEC §5 quotas).
MAX_BARS = 2_000_000
DEFAULT_TIME_BUDGET_SECONDS = 10.0


def _length(value: Value) -> int:
    return int(value.shape[0]) if isinstance(value, np.ndarray) else 0


def _numeric(value: Value, where: str) -> Array | float:
    if isinstance(value, np.ndarray):
        return value.astype(np.float64, copy=False)
    if isinstance(value, bool):
        return float(value)
    return float(value)


def _integer_arg(value: Value, function: str, position: int) -> int:
    """A length argument must be a plain positive whole number.

    Series-valued lengths are rejected rather than silently taking the first
    element: a window that changes per bar is a different indicator, and
    guessing which one the user meant would quietly change their results.
    """
    if isinstance(value, np.ndarray):
        raise EvaluationError(
            f"{function}() argument {position} must be a constant length, not a series."
        )
    number = float(value)
    if not number.is_integer():
        raise EvaluationError(f"{function}() argument {position} must be a whole number.")
    if number < 1:
        raise EvaluationError(f"{function}() argument {position} must be at least 1.")
    if number > MAX_BARS:
        raise EvaluationError(f"{function}() argument {position} is unreasonably large.")
    return int(number)


@dataclass(frozen=True, slots=True)
class FunctionSpec:
    """One whitelisted function: how many arguments and how to run it."""

    name: str
    min_args: int
    max_args: int
    handler: Callable[..., Value]
    doc: str


def _fn_sma(values: Value, length: Value) -> Value:
    return ta.sma(_as_series(values, "sma"), _integer_arg(length, "sma", 2))


def _fn_ema(values: Value, length: Value) -> Value:
    return ta.ema(_as_series(values, "ema"), _integer_arg(length, "ema", 2))


def _fn_rsi(values: Value, length: Value = 14.0) -> Value:
    return ta.rsi(_as_series(values, "rsi"), _integer_arg(length, "rsi", 2))


def _fn_highest(values: Value, length: Value) -> Value:
    return ta.highest(_as_series(values, "highest"), _integer_arg(length, "highest", 2))


def _fn_lowest(values: Value, length: Value) -> Value:
    return ta.lowest(_as_series(values, "lowest"), _integer_arg(length, "lowest", 2))


def _fn_stdev(values: Value, length: Value) -> Value:
    return ta.stdev(_as_series(values, "stdev"), _integer_arg(length, "stdev", 2))


def _fn_shift(values: Value, periods: Value = 1.0) -> Value:
    return ta.shift(_as_series(values, "shift"), _integer_arg(periods, "shift", 2))


def _fn_crossover(a: Value, b: Value) -> Value:
    return ta.crossover(
        _as_series(a, "crossover", allow_constant=True),
        _as_series(b, "crossover", allow_constant=True),
    )


def _fn_crossunder(a: Value, b: Value) -> Value:
    return ta.crossunder(
        _as_series(a, "crossunder", allow_constant=True),
        _as_series(b, "crossunder", allow_constant=True),
    )


def _fn_rising(values: Value, length: Value = 1.0) -> Value:
    return ta.rising(_as_series(values, "rising"), _integer_arg(length, "rising", 2))


def _fn_falling(values: Value, length: Value = 1.0) -> Value:
    return ta.falling(_as_series(values, "falling"), _integer_arg(length, "falling", 2))


def _fn_abs(values: Value) -> Value:
    return np.abs(_numeric(values, "abs"))  # type: ignore[return-value]


def _fn_min(a: Value, b: Value) -> Value:
    return np.minimum(_numeric(a, "min"), _numeric(b, "min"))  # type: ignore[return-value]


def _fn_max(a: Value, b: Value) -> Value:
    return np.maximum(_numeric(a, "max"), _numeric(b, "max"))  # type: ignore[return-value]


FUNCTIONS: dict[str, FunctionSpec] = {
    spec.name: spec
    for spec in (
        FunctionSpec("sma", 2, 2, _fn_sma, "Simple moving average."),
        FunctionSpec("ema", 2, 2, _fn_ema, "Exponential moving average."),
        FunctionSpec("rsi", 1, 2, _fn_rsi, "Relative strength index (default 14)."),
        FunctionSpec("highest", 2, 2, _fn_highest, "Highest value over N bars."),
        FunctionSpec("lowest", 2, 2, _fn_lowest, "Lowest value over N bars."),
        FunctionSpec("stdev", 2, 2, _fn_stdev, "Rolling standard deviation."),
        FunctionSpec("shift", 1, 2, _fn_shift, "The value N bars ago (default 1)."),
        FunctionSpec("crossover", 2, 2, _fn_crossover, "A crosses above B on this bar."),
        FunctionSpec("crossunder", 2, 2, _fn_crossunder, "A crosses below B on this bar."),
        FunctionSpec("rising", 1, 2, _fn_rising, "Rose on each of the last N bars."),
        FunctionSpec("falling", 1, 2, _fn_falling, "Fell on each of the last N bars."),
        FunctionSpec("abs", 1, 1, _fn_abs, "Absolute value."),
        FunctionSpec("min", 2, 2, _fn_min, "Smaller of two values."),
        FunctionSpec("max", 2, 2, _fn_max, "Larger of two values."),
    )
}

# `atr` and `macd` need several series, so they are bound in the context
# rather than taking bar columns as arguments.
CONTEXT_FUNCTIONS = ("atr", "macd", "macd_signal", "macd_hist", "bb_upper", "bb_lower", "bb_basis")


# The bar count of the series being evaluated. Set by Evaluator.evaluate so
# a constant like `crossover(close, 100)` can be broadcast to the right
# length without every handler having to be passed the size.
_SERIES_LENGTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "quanta_series_length", default=0
)


def _as_series(value: Value, function: str, *, allow_constant: bool = False) -> Array:
    """Coerce an argument to a series.

    A constant is broadcast only where a fixed *level* is a meaningful
    argument — `crossover(close, 100)` is an everyday condition. Everywhere
    else a scalar is a mistake: the moving average of a constant is that
    constant, so accepting `sma(5, 3)` would hide a typo rather than report
    it.
    """
    if isinstance(value, np.ndarray):
        return value.astype(np.float64, copy=False)

    if not allow_constant:
        raise EvaluationError(f"{function}() expects a series, not a single number.")

    size = _SERIES_LENGTH.get()
    if size <= 0:
        raise EvaluationError(
            f"{function}() expects a series, and there are no bars to broadcast against."
        )
    return np.full(size, float(value), dtype=np.float64)


@dataclass
class Context:
    """The series and parameters an expression may read."""

    series: dict[str, Array] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)

    def names(self) -> set[str]:
        return set(self.series) | set(self.params)

    def lookup(self, name: str) -> Value:
        if name in self.series:
            return self.series[name]
        if name in self.params:
            return float(self.params[name])
        raise EvaluationError(f"Unknown name {name!r}.")


class Evaluator:
    def __init__(self, context: Context, *, time_budget: float = DEFAULT_TIME_BUDGET_SECONDS):
        self._context = context
        self._time_budget = time_budget
        self._deadline = 0.0
        self._steps = 0

    def evaluate(self, node: Node) -> Value:
        self._deadline = time.monotonic() + self._time_budget
        self._steps = 0

        size = next((v.shape[0] for v in self._context.series.values()), 0)
        if size > MAX_BARS:
            raise LimitExceededError(
                f"{size} bars exceeds the {MAX_BARS} limit for one evaluation."
            )

        token = _SERIES_LENGTH.set(size)
        try:
            return self._eval(node)
        finally:
            _SERIES_LENGTH.reset(token)

    def _check_budget(self) -> None:
        self._steps += 1
        # Checking the clock on every node would dominate the run; every
        # 256 nodes is often enough to stop a runaway inside a second.
        if self._steps % 256 == 0 and time.monotonic() > self._deadline:
            raise LimitExceededError(f"Evaluation exceeded its {self._time_budget:g}s budget.")

    def _eval(self, node: Node) -> Value:
        self._check_budget()

        if isinstance(node, Number):
            return node.value
        if isinstance(node, Boolean):
            return node.value
        if isinstance(node, Identifier):
            return self._context.lookup(node.name)
        if isinstance(node, Unary):
            return self._eval_unary(node)
        if isinstance(node, Binary):
            return self._eval_binary(node)
        if isinstance(node, Call):
            return self._eval_call(node)

        raise EvaluationError(f"Cannot evaluate {type(node).__name__}.")

    def _eval_unary(self, node: Unary) -> Value:
        operand = self._eval(node.operand)
        if node.op == "-":
            return -_numeric(operand, "-")  # type: ignore[return-value]
        return np.logical_not(_truthy(operand))  # type: ignore[return-value]

    def _eval_binary(self, node: Binary) -> Value:
        # `and`/`or` are elementwise over series, so both sides are always
        # evaluated; there is no short-circuit to rely on.
        left = self._eval(node.left)
        right = self._eval(node.right)
        op = node.op

        if op in ("and", "or"):
            a, b = _truthy(left), _truthy(right)
            return np.logical_and(a, b) if op == "and" else np.logical_or(a, b)  # type: ignore[return-value]

        a_num, b_num = _numeric(left, op), _numeric(right, op)

        with np.errstate(divide="ignore", invalid="ignore"):
            if op == "+":
                return a_num + b_num  # type: ignore[return-value]
            if op == "-":
                return a_num - b_num  # type: ignore[return-value]
            if op == "*":
                return a_num * b_num  # type: ignore[return-value]
            if op == "/":
                # Division by zero yields NaN rather than raising: a single
                # bad bar should not abort a 100k-bar backtest.
                return np.divide(a_num, b_num)  # type: ignore[return-value]
            if op == "%":
                return np.mod(a_num, b_num)  # type: ignore[return-value]
            if op == "<":
                return np.less(a_num, b_num)  # type: ignore[return-value]
            if op == "<=":
                return np.less_equal(a_num, b_num)  # type: ignore[return-value]
            if op == ">":
                return np.greater(a_num, b_num)  # type: ignore[return-value]
            if op == ">=":
                return np.greater_equal(a_num, b_num)  # type: ignore[return-value]
            if op == "==":
                return np.equal(a_num, b_num)  # type: ignore[return-value]
            if op == "!=":
                return np.not_equal(a_num, b_num)  # type: ignore[return-value]

        raise EvaluationError(f"Unknown operator {op!r}.")

    def _eval_call(self, node: Call) -> Value:
        spec = FUNCTIONS.get(node.name)
        if spec is None:
            known = ", ".join(sorted(FUNCTIONS))
            raise EvaluationError(f"Unknown function {node.name!r}. Available: {known}.")

        if not spec.min_args <= len(node.args) <= spec.max_args:
            expected = (
                str(spec.min_args)
                if spec.min_args == spec.max_args
                else f"{spec.min_args} to {spec.max_args}"
            )
            raise EvaluationError(
                f"{node.name}() takes {expected} arguments, got {len(node.args)}."
            )

        args = [self._eval(arg) for arg in node.args]
        try:
            return spec.handler(*args)
        except EvaluationError:
            raise
        except (ValueError, TypeError, IndexError) as exc:
            raise EvaluationError(f"{node.name}(): {exc}") from exc


def _truthy(value: Value) -> BoolArray | bool:
    """Coerce to boolean the way the DSL means it.

    NaN is false: a bar where an indicator has not warmed up has no signal,
    and treating it as true would open trades on missing data.
    """
    if isinstance(value, np.ndarray):
        if value.dtype == np.bool_:
            return np.asarray(value, dtype=np.bool_)
        with np.errstate(invalid="ignore"):
            return np.asarray(np.nan_to_num(value, nan=0.0) != 0.0, dtype=np.bool_)
    return bool(value)


def evaluate(
    node: Node, context: Context, *, time_budget: float = DEFAULT_TIME_BUDGET_SECONDS
) -> Value:
    return Evaluator(context, time_budget=time_budget).evaluate(node)


def evaluate_bool(
    node: Node, context: Context, *, time_budget: float = DEFAULT_TIME_BUDGET_SECONDS
) -> BoolArray:
    """Evaluate an expression to a per-bar boolean signal."""
    result = evaluate(node, context, time_budget=time_budget)
    truthy = _truthy(result)

    if isinstance(truthy, np.ndarray):
        return truthy

    # A constant condition still has to align with the bars.
    size = next((v.shape[0] for v in context.series.values()), 0)
    return np.full(size, bool(truthy), dtype=np.bool_)


def describe_functions() -> list[dict[str, Any]]:
    """The function reference the Formula view shows."""
    return [
        {
            "name": spec.name,
            "min_args": spec.min_args,
            "max_args": spec.max_args,
            "doc": spec.doc,
        }
        for spec in sorted(FUNCTIONS.values(), key=lambda s: s.name)
    ]
