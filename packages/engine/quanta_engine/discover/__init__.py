"""The Discover engine: enumerate candidate rules, then test them (SPEC §3.2)."""

from quanta_engine.discover.primitives import (
    Primitive,
    PrimitiveKind,
    ScaleGroup,
    Series,
    Source,
    build_primitives,
    group_by_scale,
)
from quanta_engine.discover.rules import (
    Rule,
    count_raw_combinations,
    count_rules,
    count_tests,
    enumerate_rules,
)
from quanta_engine.discover.search import SearchConfig, run_search
from quanta_engine.discover.signals import compile_all, compile_primitive
from quanta_engine.discover.stats import Outcome, SearchResult, benjamini_hochberg

__all__ = [
    "Outcome",
    "Primitive",
    "PrimitiveKind",
    "Rule",
    "ScaleGroup",
    "SearchConfig",
    "SearchResult",
    "Series",
    "Source",
    "benjamini_hochberg",
    "build_primitives",
    "compile_all",
    "compile_primitive",
    "count_raw_combinations",
    "count_rules",
    "count_tests",
    "enumerate_rules",
    "group_by_scale",
    "run_search",
]
