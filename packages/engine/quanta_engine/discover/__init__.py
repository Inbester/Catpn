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

__all__ = [
    "Primitive",
    "PrimitiveKind",
    "Rule",
    "ScaleGroup",
    "Series",
    "Source",
    "build_primitives",
    "count_raw_combinations",
    "count_rules",
    "count_tests",
    "enumerate_rules",
    "group_by_scale",
]
