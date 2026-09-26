"""Research studies: leverage and costs, trade risk, robustness (SPEC §3.2)."""

from quanta_engine.research.leverage import (
    Cell,
    LeverageSweep,
    MarginModeRow,
    Recommendation,
    compare_margin_modes,
    liquidation_distance_percent,
    recommend,
    risk_of_ruin_percent,
    sweep_leverage,
)
from quanta_engine.research.robustness import (
    ParameterPoint,
    ParameterSurface,
    RiskMeasures,
    StressCase,
    kelly_fraction,
    parameter_surface,
    reshuffled_years,
    risk_measures,
    stress_tests,
    value_at_risk,
)
from quanta_engine.research.traderisk import (
    TradePoint,
    TradeRisk,
    analyse_trades,
    holding_histogram,
    liquidation_leverage,
)

__all__ = [
    "Cell",
    "LeverageSweep",
    "MarginModeRow",
    "ParameterPoint",
    "ParameterSurface",
    "Recommendation",
    "RiskMeasures",
    "StressCase",
    "TradePoint",
    "TradeRisk",
    "analyse_trades",
    "compare_margin_modes",
    "holding_histogram",
    "kelly_fraction",
    "liquidation_distance_percent",
    "liquidation_leverage",
    "parameter_surface",
    "recommend",
    "reshuffled_years",
    "risk_measures",
    "risk_of_ruin_percent",
    "stress_tests",
    "sweep_leverage",
    "value_at_risk",
]
