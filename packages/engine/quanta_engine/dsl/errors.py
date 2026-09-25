"""Errors raised while parsing or evaluating a strategy expression."""

from __future__ import annotations


class DslError(Exception):
    """Base class. Carries a position so the editor can point at the problem."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        if self.position is None:
            return self.message
        return f"{self.message} (at character {self.position + 1})"


class ParseError(DslError):
    """The expression is not valid DSL."""


class EvaluationError(DslError):
    """The expression parsed but could not be evaluated."""


class LimitExceededError(EvaluationError):
    """A sandbox limit was hit: too many nodes, bars, or too much time."""
