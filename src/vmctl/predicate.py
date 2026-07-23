"""The filter predicate tree every tier walks (docs/adr/0005, docs/adr/0007).

A deliberately tiny, pure-data tree. `dsl.py` builds it from Elasticsearch Query DSL;
`planner.py` (tier 1) and `pushdown.py` (tier 2) inspect it to narrow what gets read,
and `query.py` (tier 3) evaluates it exactly. Keeping it free of behaviour is what lets
three different consumers share one representation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    """A leaf predicate: ``field <op> value``.

    ``op`` is ``:`` (term) or one of ``>=`` ``<=`` ``>`` ``<`` (range). For ``:``, a
    ``value`` of ``*`` means *exists*, and a value containing ``*`` or ``?`` is a
    wildcard. Values are carried as text; the evaluator decides how to compare them.
    """

    field: str
    op: str
    value: str


@dataclass(frozen=True)
class Not:
    child: Node


@dataclass(frozen=True)
class And:
    """All clauses must hold. Empty = matches everything (``match_all``)."""

    clauses: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    """At least one clause must hold. Empty = matches nothing."""

    clauses: tuple[Node, ...]


Node = Match | Not | And | Or

MATCH_ALL = And(())
