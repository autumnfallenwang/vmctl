"""KQL parser — a faithful subset of Kibana Query Language (docs/adr/0005).

Parses a query string into a pure-data AST (`Match` / `Not` / `And` / `Or`) that
downstream consumers walk: the tier-3 evaluator (`vmctl.query`), and — later — the
tier-1 planner and tier-2 pushdown translator. Keeping the AST free of behaviour is
what lets those three tiers each inspect the same tree.

Supported subset:

- ``field:value`` term match, quoted values (``field:"a b"``)
- ranges ``field >= v`` / ``<=`` / ``>`` / ``<`` (spaces optional)
- wildcards (``field:00-*``) and exists (``field:*``)
- booleans ``and`` / ``or`` / ``not`` (case-insensitive), parentheses

Precedence is ``not`` > ``and`` > ``or``. Not supported (deliberate subset bounds):
implicit-AND (``a:1 b:2``), bare free-text terms, and value grouping
(``field:(a or b)``) — parenthesised *boolean* sub-expressions are supported.
"""

from __future__ import annotations

from dataclasses import dataclass

_OPERATORS = (">=", "<=", ">", "<", ":")
_KEYWORDS = {"and", "or", "not"}
# Characters that terminate a bare word (so operators/punctuation split off cleanly).
_WORD_BREAK = set(' \t\n():><"\'')


class KQLError(ValueError):
    """Raised when a query string cannot be parsed."""


@dataclass(frozen=True)
class Match:
    """A leaf predicate: ``field <op> value``. ``value == "*"`` with ``op == ":"`` is
    an exists check; a ``value`` containing ``*``/``?`` is a wildcard."""

    field: str
    op: str
    value: str


@dataclass(frozen=True)
class Not:
    child: Node


@dataclass(frozen=True)
class And:
    clauses: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    clauses: tuple[Node, ...]


Node = Match | Not | And | Or


@dataclass(frozen=True)
class _Token:
    kind: str  # "word" | "value" | "op" | "lparen" | "rparen"
    text: str


def _tokenize(query: str) -> list[_Token]:
    tokens: list[_Token] = []
    i, n = 0, len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(_Token("lparen", c))
            i += 1
            continue
        if c == ")":
            tokens.append(_Token("rparen", c))
            i += 1
            continue
        if c in "\"'":
            end = query.find(c, i + 1)
            if end == -1:
                raise KQLError(f"unterminated quoted value in {query!r}")
            tokens.append(_Token("value", query[i + 1 : end]))
            i = end + 1
            continue
        matched_op = next((op for op in _OPERATORS if query.startswith(op, i)), None)
        if matched_op is not None:
            tokens.append(_Token("op", matched_op))
            i += len(matched_op)
            continue
        start = i
        while i < n and query[i] not in _WORD_BREAK:
            i += 1
        tokens.append(_Token("word", query[start:i]))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> Node:
        if not self._tokens:
            raise KQLError("empty query")
        node = self._parse_or()
        if self._pos != len(self._tokens):
            raise KQLError(f"unexpected trailing input near {self._peek().text!r}")
        return node

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def _is_keyword(self, word: str) -> bool:
        tok = None if self._at_end() else self._peek()
        return tok is not None and tok.kind == "word" and tok.text.lower() == word

    def _parse_or(self) -> Node:
        clauses = [self._parse_and()]
        while self._is_keyword("or"):
            self._pos += 1
            clauses.append(self._parse_and())
        return clauses[0] if len(clauses) == 1 else Or(tuple(clauses))

    def _parse_and(self) -> Node:
        clauses = [self._parse_not()]
        while self._is_keyword("and"):
            self._pos += 1
            clauses.append(self._parse_not())
        return clauses[0] if len(clauses) == 1 else And(tuple(clauses))

    def _parse_not(self) -> Node:
        if self._is_keyword("not"):
            self._pos += 1
            return Not(self._parse_not())
        return self._parse_primary()

    def _parse_primary(self) -> Node:
        if self._at_end():
            raise KQLError("expected a predicate but reached end of query")
        tok = self._peek()
        if tok.kind == "lparen":
            self._pos += 1
            node = self._parse_or()
            if self._at_end() or self._peek().kind != "rparen":
                raise KQLError("unbalanced parenthesis")
            self._pos += 1
            return node
        return self._parse_match()

    def _parse_match(self) -> Node:
        field_tok = self._peek()
        if field_tok.kind != "word" or field_tok.text.lower() in _KEYWORDS:
            raise KQLError(f"expected a field name, found {field_tok.text!r}")
        self._pos += 1
        if self._at_end() or self._peek().kind != "op":
            found = "end of query" if self._at_end() else repr(self._peek().text)
            raise KQLError(f"expected an operator after {field_tok.text!r}, found {found}")
        op = self._peek().text
        self._pos += 1
        if self._at_end() or self._peek().kind not in ("word", "value"):
            found = "end of query" if self._at_end() else repr(self._peek().text)
            raise KQLError(f"expected a value after {field_tok.text!r}{op}, found {found}")
        value = self._peek().text
        self._pos += 1
        return Match(field_tok.text, op, value)


def parse(query: str) -> Node:
    """Parse a KQL query string into an AST. Raises `KQLError` on malformed input."""
    return _Parser(_tokenize(query)).parse()
