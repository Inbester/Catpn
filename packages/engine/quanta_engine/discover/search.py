"""Running a Discover search end to end (SPEC §3.2).

The order matters and is the point of the module: enumerate, evaluate on
the in-sample stretch only, correct for multiplicity, and only then score
the survivors on data that was never part of any of it. Scoring the
held-out stretch first, or correcting after looking at it, would make the
one honest number in the search as fitted as the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from quanta_engine.discover.primitives import Primitive, Series, build_primitives
from quanta_engine.discover.rules import Rule, enumerate_rules
from quanta_engine.discover.signals import compile_all, series_values
from quanta_engine.discover.stats import (
    FDR_ALPHA,
    HORIZONS,
    SIDES,
    Outcome,
    SearchResult,
    benjamini_hochberg,
    expected_false_hits,
    forward_returns,
    score,
    split_index,
)

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """What a search costs and how much of it is held back."""

    # Round trip in percent: taker in, taker out, plus slippage both ways.
    # Bitunix VIP0 taker is 0.06%, so a round trip starts at 0.12% before
    # slippage — which is more than the mean move many rules produce.
    cost_percent: float = 0.13
    alpha: float = FDR_ALPHA
    in_sample_share: float = 0.70
    horizons: tuple[int, ...] = HORIZONS
    mix_indicators: bool = False
    max_filters: int = 2


def run_search(
    series: list[Series],
    data: dict[str, Array],
    close: Array,
    *,
    config: SearchConfig | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> SearchResult:
    """Enumerate, screen in-sample, correct, then score out-of-sample."""
    config = config or SearchConfig()
    values = series_values(series, data)
    if len(close) != len(next(iter(values.values()), close)):
        raise ValueError("close must be the same length as the series")

    primitives = build_primitives(series)
    signals = compile_all(primitives, values)
    rules = list(
        enumerate_rules(
            primitives,
            max_filters=config.max_filters,
            mix_indicators=config.mix_indicators,
        )
    )

    cut = split_index(len(close), config.in_sample_share)
    in_sample = np.zeros(len(close), dtype=bool)
    in_sample[:cut] = True
    held_out = ~in_sample

    returns = {h: forward_returns(close, h) for h in config.horizons}

    outcomes: list[Outcome] = []
    total = len(rules)
    for index, rule in enumerate(rules):
        mask = _rule_mask(rule, signals)
        for horizon in config.horizons:
            for side in SIDES:
                n, gross, net, t, p, win = score(
                    mask & in_sample,
                    returns[horizon],
                    side=side,
                    cost_percent=config.cost_percent,
                )
                outcomes.append(
                    Outcome(
                        rule_key=rule.key,
                        side=side,
                        horizon=horizon,
                        signals=n,
                        mean_return_percent=gross,
                        mean_net_percent=net,
                        t_statistic=t,
                        p_value=p,
                        win_rate=win,
                    )
                )
        if progress is not None and index % 1000 == 0:
            progress(index, total)

    passed, threshold = benjamini_hochberg([o.p_value for o in outcomes], config.alpha)

    # Only now is the held-out stretch touched, and only for what survived.
    by_key = {rule.key: rule for rule in rules}
    hits: list[Outcome] = []
    for outcome, survived in zip(outcomes, passed, strict=True):
        if not survived:
            continue
        mask = _rule_mask(by_key[outcome.rule_key], signals)
        n, _, net, _, _, _ = score(
            mask & held_out,
            returns[outcome.horizon],
            side=outcome.side,
            cost_percent=config.cost_percent,
        )
        hits.append(
            replace(
                outcome,
                out_of_sample_mean_percent=net,
                out_of_sample_signals=n,
                passed_fdr=True,
            )
        )

    hits.sort(key=lambda o: o.p_value)
    if progress is not None:
        progress(total, total)

    return SearchResult(
        tested=len(outcomes),
        hits=hits,
        significant_uncorrected=sum(1 for o in outcomes if o.p_value <= config.alpha),
        expected_false_hits=expected_false_hits(len(outcomes), len(hits), config.alpha),
        threshold_p=threshold,
        in_sample_bars=int(cut),
        out_of_sample_bars=int(len(close) - cut),
    )


def _rule_mask(rule: Rule, signals: dict[str, Mask]) -> Mask:
    mask = signals[rule.trigger.key]
    for item in rule.filters:
        mask = mask & signals[item.key]
    return mask


def count_tests_for(primitives: list[Primitive], horizons: tuple[int, ...] = HORIZONS) -> int:
    """How many individual tests a search over these primitives runs."""
    return sum(1 for _ in enumerate_rules(primitives)) * len(SIDES) * len(horizons)
