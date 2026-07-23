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
import re
from datetime import datetime, timezone
from typing import Any

from vmctl.predicate import And, Match, Node, Not, Or

# A full `YYYY-MM-DDTHH:MM:SS` — coarser strings stay lexicographic.
_ISO_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


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
    # A multi-valued field matches if *any* of its values does — Elasticsearch indexes
    # every element of an array under the same field. IG's audit headers are arrays
    # (`"host": ["ig1:9080"]`), so without this a header predicate matches nothing.
    if isinstance(value, list):
        if query == "*":  # exists: an empty array indexes no value, so it is absent
            return any(v is not None for v in value)
        return any(_match_term(v, query) for v in value)
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
    if isinstance(value, list):
        return any(_match_range(v, op, query) for v in value)
    if value is None:
        return False
    left_num, right_num = _as_number(value), _as_number(query)
    left: Any
    right: Any
    if left_num is not None and right_num is not None:
        left, right = left_num, right_num
    else:
        left_at, right_at = _as_datetime(value), _as_datetime(query)
        if left_at is not None and right_at is not None:
            # Compare timestamps as instants, so a bound written `...T14:39:00Z` and a
            # value written `...T14:39:00.000+00:00` order correctly. The *remote*
            # filter still compares ISO prefixes as strings — that pass only has to be
            # a superset (ADR 0005); this one has to be exact.
            left, right = left_at, right_at
        else:
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


def _as_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing `Z` and comma millis. A value
    with no zone is read as UTC so bounds and events stay comparable."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", ".")
    if not _ISO_PREFIX.match(text):
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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
