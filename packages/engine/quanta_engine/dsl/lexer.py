"""Tokeniser for the strategy DSL.

Hand-written rather than regex-driven so every character is accounted for:
an unrecognised character is a parse error with a position, never something
silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from quanta_engine.dsl.errors import ParseError

# Keywords are matched as whole words, so `andy` is an identifier.
KEYWORDS = {"and", "or", "not", "true", "false"}

# Longest first, so `<=` is not read as `<` then `=`.
OPERATORS = (
    "<=",
    ">=",
    "==",
    "!=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "%",
)

MAX_EXPRESSION_LENGTH = 4000


class TokenType(Enum):
    NUMBER = auto()
    IDENT = auto()
    KEYWORD = auto()
    OPERATOR = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    value: str
    position: int

    def __str__(self) -> str:
        return f"{self.type.name} {self.value!r}"


def tokenize(source: str) -> list[Token]:
    """Turn an expression into tokens."""
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ParseError(
            f"Expression is {len(source)} characters; the limit is {MAX_EXPRESSION_LENGTH}."
        )

    tokens: list[Token] = []
    index = 0
    length = len(source)

    while index < length:
        char = source[index]

        if char in " \t\n\r":
            index += 1
            continue

        # Comments run to the end of the line.
        if char == "#":
            while index < length and source[index] != "\n":
                index += 1
            continue

        if char == "(":
            tokens.append(Token(TokenType.LPAREN, "(", index))
            index += 1
            continue

        if char == ")":
            tokens.append(Token(TokenType.RPAREN, ")", index))
            index += 1
            continue

        if char == ",":
            tokens.append(Token(TokenType.COMMA, ",", index))
            index += 1
            continue

        if char.isdigit() or (char == "." and index + 1 < length and source[index + 1].isdigit()):
            start = index
            seen_dot = False
            while index < length and (source[index].isdigit() or source[index] == "."):
                if source[index] == ".":
                    if seen_dot:
                        raise ParseError("A number cannot have two decimal points.", index)
                    seen_dot = True
                index += 1
            # Reject `1.2.3` and `2abc`.
            if index < length and (source[index].isalpha() or source[index] == "_"):
                raise ParseError("A number cannot be followed by a letter.", index)
            tokens.append(Token(TokenType.NUMBER, source[start:index], start))
            continue

        if char.isalpha() or char == "_":
            start = index
            while index < length and (source[index].isalnum() or source[index] == "_"):
                index += 1
            word = source[start:index]
            kind = TokenType.KEYWORD if word in KEYWORDS else TokenType.IDENT
            tokens.append(Token(kind, word, start))
            continue

        matched = next((op for op in OPERATORS if source.startswith(op, index)), None)
        if matched is not None:
            tokens.append(Token(TokenType.OPERATOR, matched, index))
            index += len(matched)
            continue

        # `=` alone is the classic typo for `==`; say so rather than
        # "unexpected character".
        if char == "=":
            raise ParseError("Use == to compare. A single = is not valid here.", index)

        if char in ".":
            raise ParseError("Attribute access is not allowed in a strategy expression.", index)

        raise ParseError(f"Unexpected character {char!r}.", index)

    tokens.append(Token(TokenType.EOF, "", length))
    return tokens
