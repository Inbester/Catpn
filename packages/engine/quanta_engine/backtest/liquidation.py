"""Liquidation price under tiered maintenance margin (SPEC §6).

Bitunix liquidates on the *mark* price, not the last price, and the
maintenance margin rate depends on which notional tier the position falls
in. Both matter: using the last price liquidates too early or too late, and
a flat MMR understates risk on large positions — the exact cases a trader
sizes around.

The formula from SPEC §6 for an isolated long::

    liq ~ entry x (1 - (margin - maint) / (margin x lev))

Rearranged here in terms of notional so the tier lookup is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionTier:
    """One row of the maintenance-margin ladder."""

    level: int
    start_value: float
    end_value: float
    max_leverage: int
    maintenance_margin_rate: float
    # Bitunix publishes a rate per tier; the deduction keeps the piecewise
    # function continuous at tier boundaries.
    maintenance_amount: float = 0.0


# A single flat tier, for tests and venues that do not publish a ladder.
FLAT_TIER = (PositionTier(1, 0.0, float("inf"), 125, 0.005),)


def tier_for_notional(tiers: tuple[PositionTier, ...], notional: float) -> PositionTier:
    """The tier a position of this notional falls into."""
    if not tiers:
        return FLAT_TIER[0]

    magnitude = abs(notional)
    for tier in tiers:
        if tier.start_value <= magnitude < tier.end_value:
            return tier
    # Past the published ladder: the last tier is the most conservative.
    return tiers[-1]


def maintenance_margin(tiers: tuple[PositionTier, ...], notional: float) -> float:
    """Maintenance margin required to hold ``notional``."""
    tier = tier_for_notional(tiers, notional)
    return abs(notional) * tier.maintenance_margin_rate - tier.maintenance_amount


def liquidation_price(
    *,
    entry_price: float,
    quantity: float,
    margin: float,
    is_long: bool,
    tiers: tuple[PositionTier, ...] = FLAT_TIER,
) -> float:
    """The mark price at which the position is liquidated.

    ``margin`` is the collateral backing the position: the isolated margin,
    or the whole account balance in cross mode (SPEC §6).

    Returns 0 for a long that cannot be liquidated by a fall to zero, and
    infinity for a short with enough margin to survive any rise.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    notional = entry_price * quantity
    maint = maintenance_margin(tiers, notional)

    # Liquidation is where equity falls to the maintenance requirement:
    #   margin + pnl = maint,  pnl = ±quantity x (price - entry)
    if is_long:
        price = entry_price - (margin - maint) / quantity
        return max(price, 0.0)

    price = entry_price + (margin - maint) / quantity
    return price if price > 0 else float("inf")


def liquidation_distance_percent(entry_price: float, liq_price: float, is_long: bool) -> float:
    """How far price must move against the position before liquidation."""
    if entry_price <= 0:
        return 0.0
    if liq_price in (0.0, float("inf")):
        return 100.0
    move = (entry_price - liq_price) if is_long else (liq_price - entry_price)
    return max(0.0, move / entry_price * 100.0)
