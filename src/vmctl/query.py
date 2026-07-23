"""Tier-3 predicate evaluation — exact, client-side (docs/adr/0005).

The authoritative pass: evaluate a parsed KQL AST against fully-built ECS events in
memory. Tiers 1 and 2 (planner / remote pushdown) are only ever a *sound superset* —
they narrow what gets read but never decide a match. This module does.

Field paths resolve against the ECS event both ways round: nested
(``{"http": {"response": {"statusCode": 500}}}``) and flat-dotted
(``{"http.response.statusCode": 500}``), because Elasticsearch treats the two
identically and merged log JSON may use either.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from vmctl.kql import And, Match, Node, Not, Or


def resolve_field(event: dict[str, Any], path: str) -> Any:
    """Resolve a dotted ECS field path. Returns `None` when the field is absent.

    At each level the longest flat-dotted key wins before descending a segment, so
    both nested and flattened representations resolve.
    """
    parts = path.split(".")
    current: Any = event
    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            return None
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if key in current:
                current = current[key]
                i = j
                break
        else:
            return None
    return current


def matches(node: Node, event: dict[str, Any]) -> bool:
    """Evaluate a parsed KQL node against one ECS event."""
    if isinstance(node, Match):
        value = resolve_field(event, node.field)
        if node.op == ":":
            return _match_term(value, node.value)
        return _match_range(value, node.op, node.value)
    if isinstance(node, Not):
        return not matches(node.child, event)
    if isinstance(node, And):
        return all(matches(c, event) for c in node.clauses)
    if isinstance(node, Or):
        return any(matches(c, event) for c in node.clauses)
    raise TypeError(f"unsupported query node: {node!r}")


def _match_term(value: Any, query: str) -> bool:
    if query == "*":  # exists
        return value is not None
    if value is None:
        return False
    if "*" in query or "?" in query:
        return fnmatch.fnmatchcase(str(value), query)
    if isinstance(value, bool):
        return str(value).lower() == query.lower()
    left, right = _as_number(value), _as_number(query)
    if left is not None and right is not None:
        return left == right
    return str(value) == query


def _match_range(value: Any, op: str, query: str) -> bool:
    if value is None:
        return False
    left_num, right_num = _as_number(value), _as_number(query)
    left: Any
    right: Any
    if left_num is not None and right_num is not None:
        left, right = left_num, right_num
    else:
        # Lexicographic — which is exactly right for the uniform UTC ISO timestamps
        # vmctl parses (ADR 0005's time-window mechanics).
        left, right = str(value), query
    if op == ">=":
        return bool(left >= right)
    if op == "<=":
        return bool(left <= right)
    if op == ">":
        return bool(left > right)
    if op == "<":
        return bool(left < right)
    raise ValueError(f"unsupported range operator: {op!r}")


def _as_number(value: Any) -> float | None:
    """Numeric view of a value, or `None` if it isn't numeric. Booleans are not
    numbers here — `enabled:true` should compare as a word, not as 1."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
