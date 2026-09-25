"""The strategy DSL: parsing, the sandbox, and evaluation."""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.dsl.errors import EvaluationError, LimitExceededError, ParseError
from quanta_engine.dsl.evaluator import Context, evaluate, evaluate_bool
from quanta_engine.dsl.nodes import Binary, Call, Identifier, Number, functions, identifiers
from quanta_engine.dsl.parser import MAX_NODES, parse

CLOSE = np.array([10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0])


def context(**params: float) -> Context:
    return Context(
        series={
            "close": CLOSE,
            "open": CLOSE - 0.5,
            "high": CLOSE + 1.0,
            "low": CLOSE - 1.0,
        },
        params=params,
    )


class TestParsing:
    def test_parses_a_comparison(self) -> None:
        node = parse("close > 100")
        assert isinstance(node, Binary)
        assert node.op == ">"

    def test_respects_arithmetic_precedence(self) -> None:
        # 2 + 3 * 4 must parse as 2 + (3 * 4).
        assert str(parse("2 + 3 * 4")) == "(2.0 + (3.0 * 4.0))"

    def test_parentheses_override_precedence(self) -> None:
        assert str(parse("(2 + 3) * 4")) == "((2.0 + 3.0) * 4.0)"

    def test_and_binds_tighter_than_or(self) -> None:
        assert str(parse("a or b and c")) == "(a or (b and c))"

    def test_not_applies_to_the_comparison(self) -> None:
        assert str(parse("not close > 5")) == "(not (close > 5.0))"

    def test_parses_nested_calls(self) -> None:
        node = parse("crossover(ema(close, 12), ema(close, 26))")
        assert isinstance(node, Call)
        assert functions(node) == {"crossover", "ema"}
        assert identifiers(node) == {"close"}

    def test_ignores_comments_and_whitespace(self) -> None:
        a = parse("close > 100")
        b = parse("  close   >   100   # a comment\n")
        assert str(a) == str(b)

    def test_accepts_booleans(self) -> None:
        assert str(parse("true and not false")) == "(true and (not false))"

    @pytest.mark.parametrize(
        ("source", "fragment"),
        [
            ("", "empty"),
            ("close >", "ends unexpectedly"),
            ("close > > 5", "Unexpected"),
            ("(close > 5", "closing parenthesis"),
            ("close > 5)", "Unexpected"),
            ("a < b < c", "Chained comparisons"),
            ("close = 5", "Use == to compare"),
            ("close.value", "Attribute access"),
            ("1.2.3", "two decimal points"),
            ("2abc", "followed by a letter"),
            ("close $ 5", "Unexpected character"),
            ("and close", "cannot start an expression"),
        ],
    )
    def test_rejects_bad_input(self, source: str, fragment: str) -> None:
        with pytest.raises(ParseError, match=fragment):
            parse(source)

    def test_reports_a_position(self) -> None:
        with pytest.raises(ParseError) as caught:
            parse("close > $")
        assert caught.value.position == 8

    def test_rejects_an_over_long_expression(self) -> None:
        with pytest.raises(ParseError, match="characters"):
            parse("close + " * 3000 + "1")

    def test_rejects_an_over_complex_expression(self) -> None:
        # Single-letter names and no spaces, so this trips the node cap
        # rather than the character cap.
        source = "+".join(["a"] * (MAX_NODES // 2 + 60))
        with pytest.raises(ParseError, match=f"{MAX_NODES}"):
            parse(source)

    def test_rejects_deep_nesting(self) -> None:
        with pytest.raises(ParseError, match="nests deeper"):
            parse("(" * 100 + "close" + ")" * 100)


class TestSandbox:
    """SPEC §5: user code is never executed, only the DSL runs."""

    @pytest.mark.parametrize(
        "source",
        [
            "__import__('os')",
            "open('/etc/passwd')",
            "eval('1+1')",
            "exec('x=1')",
            "globals()",
            "getattr(close, 'shape')",
            "compile('1', '', 'eval')",
        ],
    )
    def test_dangerous_builtins_are_not_callable(self, source: str) -> None:
        """These parse as ordinary calls and then fail: no such function."""
        node = parse(source) if "'" not in source else None
        if node is None:
            # String literals are not in the grammar at all.
            with pytest.raises(ParseError):
                parse(source)
            return
        with pytest.raises(EvaluationError, match="Unknown function"):
            evaluate(node, context())

    def test_attribute_access_is_rejected_by_the_lexer(self) -> None:
        with pytest.raises(ParseError, match="Attribute access"):
            parse("close.__class__.__mro__")

    def test_unknown_names_are_rejected(self) -> None:
        with pytest.raises(EvaluationError, match="Unknown name"):
            evaluate(parse("secret_key"), context())

    def test_a_time_budget_stops_a_runaway(self) -> None:
        # A deeply repeated expression over a large series, with no budget.
        big = Context(series={"close": np.random.default_rng(0).normal(size=50_000)})
        expression = parse(" + ".join(["close"] * 400))
        with pytest.raises(LimitExceededError, match="budget"):
            evaluate(expression, big, time_budget=0.001)


class TestEvaluation:
    def test_compares_a_series_to_a_constant(self) -> None:
        result = evaluate_bool(parse("close > 11"), context())
        assert result.tolist() == [False, False, True, False, False, False, True, True, True, True]

    def test_reads_a_parameter(self) -> None:
        result = evaluate_bool(parse("close > level"), context(level=13.0))
        assert result.tolist() == [False] * 8 + [True, True]

    def test_combines_conditions(self) -> None:
        result = evaluate_bool(parse("close > 10 and close < 13"), context())
        assert result.tolist() == [
            False,
            True,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
        ]

    def test_crossover_against_a_constant_level(self) -> None:
        """`crossover(close, 100)` must broadcast the level across the bars."""
        result = evaluate_bool(parse("crossover(close, 11.5)"), context())
        # 11 -> 12 at index 2, and 11 -> 12 at index 6.
        assert result.tolist() == [
            False,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
        ]

    def test_nan_is_false(self) -> None:
        """An indicator that has not warmed up is not a signal."""
        result = evaluate_bool(parse("ema(close, 8) > 0"), context())
        # The first seven bars have no EMA yet.
        assert result.tolist()[:7] == [False] * 7
        assert result.tolist()[7] is True

    def test_division_by_zero_yields_nan_not_an_exception(self) -> None:
        """One bad bar must not abort a long backtest."""
        result = evaluate(parse("close / 0"), context())
        assert np.all(np.isinf(np.asarray(result)) | np.isnan(np.asarray(result)))

    def test_arithmetic_on_series(self) -> None:
        result = evaluate(parse("(high + low) / 2"), context())
        assert np.allclose(np.asarray(result), CLOSE)

    @pytest.mark.parametrize(
        ("source", "fragment"),
        [
            ("nope(close)", "Unknown function"),
            ("sma(close)", "takes 2 arguments"),
            ("sma(close, 1, 2)", "takes 2 arguments"),
            ("sma(close, close)", "constant length"),
            ("sma(close, 0)", "at least 1"),
            ("sma(close, 1.5)", "whole number"),
            ("sma(5, 3)", "expects a series"),
        ],
    )
    def test_reports_misuse_clearly(self, source: str, fragment: str) -> None:
        with pytest.raises(EvaluationError, match=fragment):
            evaluate(parse(source), context())

    def test_shift_cannot_look_forward(self) -> None:
        """A negative shift would read the future."""
        with pytest.raises(EvaluationError, match="at least 1"):
            evaluate(parse("shift(close, -1)"), context())

    def test_a_constant_condition_still_aligns_to_the_bars(self) -> None:
        result = evaluate_bool(parse("true"), context())
        assert result.shape == CLOSE.shape
        assert result.all()


class TestNodes:
    def test_identical_expressions_produce_equal_trees(self) -> None:
        assert parse("close > 5") == parse("close  >  5")

    def test_different_expressions_differ(self) -> None:
        assert parse("close > 5") != parse("close > 6")

    def test_trees_are_hashable(self) -> None:
        assert len({parse("close > 5"), parse("close > 5"), parse("close > 6")}) == 2

    def test_identifiers_and_functions_are_discoverable(self) -> None:
        node = parse("ema(close, n) > sma(high, 10)")
        assert identifiers(node) == {"close", "high", "n"}
        assert functions(node) == {"ema", "sma"}

    def test_number_and_identifier_render_back(self) -> None:
        assert str(Number(5.0)) == "5.0"
        assert str(Identifier("close")) == "close"
