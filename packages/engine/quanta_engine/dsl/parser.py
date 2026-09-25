"""Recursive-descent parser for the strategy DSL.

Grammar, loosest binding first::

    expression  := or_expr
    or_expr     := and_expr ("or" and_expr)*
    and_expr    := not_expr ("and" not_expr)*
    not_expr    := "not" not_expr | comparison
    comparison  := additive (("<" | "<=" | ">" | ">=" | "==" | "!=") additive)?
    additive    := multiplicative (("+" | "-") multiplicative)*
    multiplicative := unary (("*" | "/" | "%") unary)*
    unary       := "-" unary | primary
    primary     := NUMBER | "true" | "false" | IDENT "(" args ")" | IDENT
                 | "(" expression ")"

Comparison is deliberately non-associative: ``a < b < c`` reads as
mathematics to a human and as ``(a < b) < c`` to a parser, so it is rejected
rather than quietly given the wrong meaning.
"""

from __future__ import annotations

from quanta_engine.dsl.errors import ParseError
from quanta_engine.dsl.lexer import Token, TokenType, tokenize
from quanta_engine.dsl.nodes import (
    Binary,
    Boolean,
    Call,
    Identifier,
    Node,
    Number,
    Unary,
)

# A guard against a pathological expression, not a style limit.
MAX_NODES = 2000
MAX_CALL_ARGS = 8
MAX_DEPTH = 64

COMPARISONS: frozenset[str] = frozenset({"<", "<=", ">", ">=", "==", "!="})


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._index = 0
        self._depth = 0
        self._nodes = 0

    def _count_node(self) -> None:
        """Budget nodes as they are built.

        Counting only at the end would mean constructing the whole tree
        first, and a long enough expression exhausts the stack before the
        cap is ever reached.
        """
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise ParseError(f"Expression is too complex; the limit is {MAX_NODES} nodes.")

    # --- token helpers --------------------------------------------------

    @property
    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current
        if token.type is not TokenType.EOF:
            self._index += 1
        return token

    def _matches(self, type_: TokenType, *values: str) -> bool:
        token = self._current
        if token.type is not type_:
            return False
        return not values or token.value in values

    def _expect(self, type_: TokenType, description: str) -> Token:
        if self._current.type is not type_:
            found = self._current.value or "the end of the expression"
            raise ParseError(f"Expected {description}, found {found!r}.", self._current.position)
        return self._advance()

    # --- grammar --------------------------------------------------------

    def parse(self) -> Node:
        if self._current.type is TokenType.EOF:
            raise ParseError("The expression is empty.")

        node = self._or_expr()
        if self._current.type is not TokenType.EOF:
            raise ParseError(
                f"Unexpected {self._current.value!r} after the expression.",
                self._current.position,
            )
        return node

    def _or_expr(self) -> Node:
        node = self._and_expr()
        while self._matches(TokenType.KEYWORD, "or"):
            self._advance()
            self._count_node()
            node = Binary("or", node, self._and_expr())
        return node

    def _and_expr(self) -> Node:
        node = self._not_expr()
        while self._matches(TokenType.KEYWORD, "and"):
            self._advance()
            self._count_node()
            node = Binary("and", node, self._not_expr())
        return node

    def _not_expr(self) -> Node:
        if self._matches(TokenType.KEYWORD, "not"):
            self._advance()
            self._count_node()
            return Unary("not", self._not_expr())
        return self._comparison()

    def _comparison(self) -> Node:
        node = self._additive()
        if self._current.type is TokenType.OPERATOR and self._current.value in COMPARISONS:
            op = self._advance().value
            self._count_node()
            right = self._additive()
            node = Binary(op, node, right)  # type: ignore[arg-type]

            # Chained comparisons mean something different to a parser than
            # to a reader, so refuse rather than guess.
            if self._current.type is TokenType.OPERATOR and self._current.value in COMPARISONS:
                raise ParseError(
                    "Chained comparisons are not allowed. Write `a > b and b > c` instead.",
                    self._current.position,
                )
        return node

    def _additive(self) -> Node:
        node = self._multiplicative()
        while self._current.type is TokenType.OPERATOR and self._current.value in ("+", "-"):
            op = self._advance().value
            self._count_node()
            node = Binary(op, node, self._multiplicative())  # type: ignore[arg-type]
        return node

    def _multiplicative(self) -> Node:
        node = self._unary()
        while self._current.type is TokenType.OPERATOR and self._current.value in ("*", "/", "%"):
            op = self._advance().value
            self._count_node()
            node = Binary(op, node, self._unary())  # type: ignore[arg-type]
        return node

    def _unary(self) -> Node:
        if self._current.type is TokenType.OPERATOR and self._current.value == "-":
            self._advance()
            self._count_node()
            return Unary("-", self._unary())
        return self._primary()

    def _primary(self) -> Node:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise ParseError(f"Expression nests deeper than {MAX_DEPTH} levels.")
        try:
            return self._primary_inner()
        finally:
            self._depth -= 1

    def _primary_inner(self) -> Node:
        self._count_node()
        token = self._current

        if token.type is TokenType.NUMBER:
            self._advance()
            try:
                return Number(float(token.value))
            except ValueError as exc:
                raise ParseError(f"{token.value!r} is not a number.", token.position) from exc

        if token.type is TokenType.KEYWORD and token.value in ("true", "false"):
            self._advance()
            return Boolean(token.value == "true")

        if token.type is TokenType.KEYWORD:
            raise ParseError(f"{token.value!r} cannot start an expression.", token.position)

        if token.type is TokenType.IDENT:
            self._advance()
            if self._matches(TokenType.LPAREN):
                return self._call(token)
            return Identifier(token.value)

        if token.type is TokenType.LPAREN:
            self._advance()
            node = self._or_expr()
            self._expect(TokenType.RPAREN, "a closing parenthesis")
            return node

        if token.type is TokenType.EOF:
            raise ParseError("The expression ends unexpectedly.", token.position)

        raise ParseError(f"Unexpected {token.value!r}.", token.position)

    def _call(self, name_token: Token) -> Node:
        self._expect(TokenType.LPAREN, "an opening parenthesis")
        args: list[Node] = []

        if not self._matches(TokenType.RPAREN):
            args.append(self._or_expr())
            while self._matches(TokenType.COMMA):
                self._advance()
                args.append(self._or_expr())
                if len(args) > MAX_CALL_ARGS:
                    raise ParseError(
                        f"{name_token.value}() takes at most {MAX_CALL_ARGS} arguments.",
                        name_token.position,
                    )

        self._expect(TokenType.RPAREN, "a closing parenthesis")
        return Call(name_token.value, tuple(args))


def parse(source: str) -> Node:
    """Parse an expression into an AST. Raises :class:`ParseError`."""
    return Parser(tokenize(source)).parse()
