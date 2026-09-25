"""Process-wide handle to the market-data service.

One instance per process owns the single upstream exchange connection
(SPEC §4). Routes reach it through here rather than constructing their own,
which would open a second socket and blow the venue's message budget.
"""

from __future__ import annotations

from typing import Any

_service: Any | None = None


def set_market_service(service: Any | None) -> None:
    global _service
    _service = service


def get_market_service() -> Any | None:
    return _service
