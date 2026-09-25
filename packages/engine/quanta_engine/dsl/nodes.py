"""AST nodes for the strategy DSL.

SPEC §4/D13: user code is *never* executed. An expression is parsed into
these nodes and evaluated by a walker that only knows about them, so there
is no path from a strategy to arbitrary Python — no attribute access, no
imports, no calls except the whitelisted functions.

Nodes are frozen and hashable so a strategy's content hash can be taken
straight from its tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Operators the grammar accepts. Anything else is a parse error.
BinaryOp = Literal["+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!=", "and", "or"]
UnaryOp = Literal["-", "not"]


@dataclass(frozen=True, slots=True)
class Number:
    value: float

    def __str__(self) -> str:
        return repr(self.value)


@dataclass(frozen=True, slots=True)
class Boolean:
    value: bool

    def __str__(self) -> str:
        return "true" if self.value else "false"


@dataclass(frozen=True, slots=True)
class Identifier:
    """A series or parameter name, e.g. ``close`` or ``rsi_length``."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Call:
    """A whitelisted function call, e.g. ``ema(close, 20)``."""

    name: str
    args: tuple[Node, ...]

    def __str__(self) -> str:
        return f"{self.name}({', '.join(str(a) for a in self.args)})"


@dataclass(frozen=True, slots=True)
class Unary:
    op: UnaryOp
    operand: Node

    def __str__(self) -> str:
        space = " " if self.op == "not" else ""
        return f"({self.op}{space}{self.operand})"


@dataclass(frozen=True, slots=True)
class Binary:
    op: BinaryOp
    left: Node
    right: Node

    def __str__(self) -> str:
        return f"({self.left} {self.op} {self.right})"


Node = Number | Boolean | Identifier | Call | Unary | Binary


def walk(node: Node) -> list[Node]:
    """Every node in the tree, parents before children.

    Iterative on purpose. A chain like ``a + a + a + ...`` nests as deeply
    as it is long, and recursing over one would raise RecursionError —
    turning a user's bad expression into a crashed worker rather than a
    parse error.
    """
    found: list[Node] = []
    stack: list[Node] = [node]

    while stack:
        current = stack.pop()
        found.append(current)

        if isinstance(current, Call):
            stack.extend(reversed(current.args))
        elif isinstance(current, Unary):
            stack.append(current.operand)
        elif isinstance(current, Binary):
            # Pushed right-then-left so the left subtree comes out first.
            stack.append(current.right)
            stack.append(current.left)

    return found


def identifiers(node: Node) -> set[str]:
    """Every identifier the expression reads."""
    return {n.name for n in walk(node) if isinstance(n, Identifier)}


def functions(node: Node) -> set[str]:
    """Every function the expression calls."""
    return {n.name for n in walk(node) if isinstance(n, Call)}


def node_count(node: Node) -> int:
    return len(walk(node))
