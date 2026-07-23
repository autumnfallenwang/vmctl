"""Compact Query DSL builders for tests.

Tests go through `parse_dsl`, the real (and only) input path, rather than constructing
AST nodes by hand — so a change to the front end can't quietly stop being covered.
"""

from __future__ import annotations

from typing import Any

from vmctl.predicate import Node
from vmctl.dsl import parse_dsl


def q(clause: dict[str, Any]) -> Node:
    return parse_dsl(clause)


def term(field: str, value: Any) -> dict[str, Any]:
    return {"term": {field: value}}


def rng(field: str, **bounds: Any) -> dict[str, Any]:
    return {"range": {field: bounds}}


def exists(field: str) -> dict[str, Any]:
    return {"exists": {"field": field}}


def wildcard(field: str, value: str) -> dict[str, Any]:
    return {"wildcard": {field: value}}


def all_of(*clauses: dict[str, Any]) -> dict[str, Any]:
    return {"bool": {"filter": list(clauses)}}


def any_of(*clauses: dict[str, Any]) -> dict[str, Any]:
    return {"bool": {"should": list(clauses)}}


def none_of(*clauses: dict[str, Any]) -> dict[str, Any]:
    return {"bool": {"must_not": list(clauses)}}
