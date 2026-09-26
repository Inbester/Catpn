"""Turning validation failures into sentences a person can act on.

Pydantic's own messages are written for the developer holding the schema:
"String should have at least 1 character" is precise and useless to
someone looking at a form, because it does not say *which* field, or what
to do about it. This module converts the machine's answer into a human
one, once, for every endpoint.

The shape of the response does not change — still `{"detail": ...}`, still
422 — so nothing that reads errors has to be touched. Only the words do.
"""

from __future__ import annotations

from typing import Any

#: Fields whose attribute name is not what a person calls them.
FIELD_LABELS = {
    "display_name": "Name",
    "api_key": "API key",
    "api_secret": "API secret",
    "totp": "Code",
    "code": "Code",
    "email": "Email",
    "password": "Password",
    "client_id": "Client id",
    "setup_id": "Setup",
    "exchange_key_id": "Exchange key",
    "max_position_notional": "Max position",
    "max_daily_loss": "Max daily loss",
    "max_drawdown_percent": "Max drawdown",
    "max_leverage": "Max leverage",
    "max_orders_per_minute": "Max orders per minute",
}


def field_label(location: tuple[Any, ...]) -> str:
    """The name of the field a person would recognise.

    `loc` is like ("body", "display_name") or ("body", "limits", "max_leverage").
    The wrapper segments are dropped and the last name is used, because
    that is the box on the screen.
    """
    names = [str(part) for part in location if isinstance(part, str)]
    names = [name for name in names if name not in ("body", "query", "path", "header")]
    if not names:
        return "That value"
    last = names[-1]
    if last in FIELD_LABELS:
        return FIELD_LABELS[last]
    return last.replace("_", " ").capitalize()


def humanise(error: dict[str, Any]) -> str:
    """One Pydantic error as a sentence."""
    label = field_label(tuple(error.get("loc") or ()))
    kind = str(error.get("type") or "")
    context = error.get("ctx") or {}

    if kind == "missing":
        return f"{label} is required."

    if kind == "string_too_short":
        minimum = context.get("min_length")
        # A minimum of one means "not empty", which reads as required
        # rather than as a length rule.
        if minimum in (None, 1):
            return f"{label} is required."
        return f"{label} must be at least {minimum} characters."

    if kind == "string_too_long":
        return f"{label} must be at most {context.get('max_length')} characters."

    if kind in ("greater_than", "greater_than_equal"):
        word = "more than" if kind == "greater_than" else "at least"
        return f"{label} must be {word} {context.get('gt', context.get('ge'))}."

    if kind in ("less_than", "less_than_equal"):
        word = "less than" if kind == "less_than" else "at most"
        return f"{label} must be {word} {context.get('lt', context.get('le'))}."

    if kind.startswith("value_error") and "email" in str(error.get("msg", "")).lower():
        return "That email address does not look right."

    if kind in ("int_parsing", "decimal_parsing", "float_parsing", "int_type", "float_type"):
        return f"{label} must be a number."

    if kind == "bool_parsing":
        return f"{label} must be true or false."

    if kind == "literal_error":
        allowed = context.get("expected")
        return f"{label} must be one of {allowed}." if allowed else f"{label} is not valid."

    if kind == "uuid_parsing":
        return f"{label} is not a valid id."

    if kind == "json_invalid":
        return "The request body was not valid JSON."

    # Anything unmapped still names the field, which is the part Pydantic
    # leaves out and the part the user needs.
    message = str(error.get("msg") or "is not valid").rstrip(".")
    lowered = message[0].lower() + message[1:] if message else "is not valid"
    return f"{label}: {lowered}."


def summarise(errors: list[dict[str, Any]]) -> str:
    """Every failure in one sentence.

    All of them, not just the first: a form that reveals its problems one
    at a time makes the user submit four times to learn four things.
    """
    seen: list[str] = []
    for error in errors:
        sentence = humanise(error)
        if sentence not in seen:
            seen.append(sentence)
    return " ".join(seen) if seen else "That request was not valid."
