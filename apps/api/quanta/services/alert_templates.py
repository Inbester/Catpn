"""Rendering an alert message (SPEC §3.4).

Templates are `{{variable}}` substitution and nothing else — no
expressions, no conditionals, no loops. A template language that can
compute is a template language that can be made to leak, and these strings
are user-supplied and rendered on the server.

Every message ends with "Not financial advice", in the message's own
language, and that line is appended rather than left to the template. A
user can rewrite everything above it; they cannot remove it, because the
disclaimer is the product's statement and not theirs.
"""

from __future__ import annotations

import re
from typing import Any

# Only these are substituted. An unknown variable is left visible as
# written rather than blanked, so a typo shows up in the test send instead
# of producing a message with a hole in it.
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

DISCLAIMER = {
    "en": "Not financial advice.",
    "fa": "این توصیهٔ مالی نیست.",
}

DEFAULT_TEMPLATE = {
    "en": (
        "{{side_icon}} {{SIDE}} {{symbol}} {{tf}}\n"
        "{{strategy}} · {{version}}\n"
        "Price {{price}} · SL {{sl}} ({{sl_pct}}) · TP {{tp}} ({{tp_pct}})\n"
        "{{size}} at {{leverage}} · {{time_tehran}}"
    ),
    "fa": (
        "{{side_icon}} {{SIDE}} {{symbol}} {{tf}}\n"
        "{{strategy}} · {{version}}\n"
        "قیمت {{price}} · حد ضرر {{sl}} ({{sl_pct}}) · حد سود {{tp}} ({{tp_pct}})\n"
        "{{size}} با اهرم {{leverage}} · {{time_tehran}}"
    ),
}

SIDE_ICONS = {"long": "🟢", "short": "🔴", "exit": "⚪️"}


def render(template: str, context: dict[str, Any], locale: str = "en") -> str:
    """Substitute the known variables and append the disclaimer."""
    body = template.strip() or DEFAULT_TEMPLATE.get(locale, DEFAULT_TEMPLATE["en"])

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in context:
            # Left as written: a typo should be visible in a test send,
            # not silently produce a message with a hole in it.
            return match.group(0)
        value = context[name]
        return "" if value is None else str(value)

    rendered = VARIABLE_PATTERN.sub(substitute, body)
    disclaimer = DISCLAIMER.get(locale, DISCLAIMER["en"])
    # Appended, not part of the template: a user can rewrite everything
    # above this line but cannot remove it.
    return f"{rendered}\n\n{disclaimer}"


def build_context(
    *,
    side: str,
    symbol: str,
    interval: str,
    price: float,
    strategy: str = "",
    version: str = "",
    stop_loss: float | None = None,
    take_profit: float | None = None,
    size: str = "",
    leverage: str = "",
    pnl: str = "",
    indicators: dict[str, float] | None = None,
    time_tehran: str = "",
    chart_link: str = "",
) -> dict[str, Any]:
    """The variables SPEC §3.4 names, with the derived ones filled in."""

    def percent(level: float | None) -> str:
        if level is None or price <= 0:
            return "—"
        return f"{(level - price) / price * 100:+.2f}%"

    context: dict[str, Any] = {
        "side_icon": SIDE_ICONS.get(side.lower(), "•"),
        "SIDE": side.upper(),
        "side": side.lower(),
        "symbol": symbol,
        "tf": interval,
        "strategy": strategy,
        # Twelve characters of the content hash: enough to identify the
        # version in a message, short enough not to dominate it.
        "version": version[:12],
        "price": f"{price:g}",
        "sl": "—" if stop_loss is None else f"{stop_loss:g}",
        "sl_pct": percent(stop_loss),
        "tp": "—" if take_profit is None else f"{take_profit:g}",
        "tp_pct": percent(take_profit),
        "size": size,
        "leverage": leverage,
        "pnl": pnl,
        "time_tehran": time_tehran,
        "chart_link": chart_link,
    }
    for name, value in (indicators or {}).items():
        context[name] = f"{value:.2f}"
    return context


def merge_messages(messages: list[str], locale: str = "en") -> str:
    """Fold a burst into one message (SPEC §3.4).

    Signals within the merge window become a single send. Keeping the
    first and counting the rest, rather than concatenating, because a
    burst is usually one event seen several times and a wall of near
    identical text is harder to read than one line plus a count.
    """
    if not messages:
        return ""
    if len(messages) == 1:
        return messages[0]

    extra = len(messages) - 1
    more = (
        f"+{extra} more signal{'s' if extra != 1 else ''} in the same window"
        if locale != "fa"
        else f"+{extra} سیگنال دیگر در همین بازه"
    )
    first = messages[0]
    disclaimer = DISCLAIMER.get(locale, DISCLAIMER["en"])
    # The disclaimer stays at the end, so the count goes above it.
    if first.endswith(disclaimer):
        head = first[: -len(disclaimer)].rstrip()
        return f"{head}\n{more}\n\n{disclaimer}"
    return f"{first}\n{more}"
