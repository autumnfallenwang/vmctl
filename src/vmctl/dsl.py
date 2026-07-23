"""Elasticsearch Query DSL — the sole query input (docs/adr/0007).

Parses the same JSON that would go in the body of ``POST /<index>/_search`` into the
shared filter AST. vmctl has **no index, no field mappings and no analyzer**, so it
implements the constructs whose meaning survives that absence and *rejects* the rest
with an explicit error naming them.

Supported: ``bool`` (``filter``/``must``/``must_not``/``should`` + ``minimum_should_match``),
``term``, ``terms``, ``range``, ``exists``, ``wildcard``, ``prefix``, ``match_all``.

Rejected on purpose — see ADR 0007 for the reasoning:

- the full-text family (``match``, ``match_phrase``, ``multi_match``, ``query_string``)
  means *analyzed* comparison; without an analyzer, quietly doing exact comparison
  would look like Elasticsearch and behave differently
- scoring-only constructs (``boost``, ``function_score``, ``dis_max``) are meaningless
  without ranking, which vmctl does not do
- index-topology constructs (``nested``, ``has_child``, joins) have no analogue

An unsupported construct is always an error, never a silent no-op: a filter that
silently matched everything would return plausible-looking wrong results.
"""

from __future__ import annotations

import json
import re
from typing import Any, NoReturn

from vmctl.predicate import MATCH_ALL, And, Match, Node, Not, Or

# `size`, `sort` etc. imply behaviour vmctl does not have; dropping them would mislead.
_BODY_KEYS = {"query"}
_RANGE_OPS = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}
# Elasticsearch date math (`now-1d/d`, `2020||+1M`) — absolute ISO-8601 only here.
_DATE_MATH = re.compile(r"^now\b|\|\|")

_FULLTEXT = {
    "match",
    "match_phrase",
    "match_phrase_prefix",
    "match_bool_prefix",
    "multi_match",
    "query_string",
    "simple_query_string",
    "combined_fields",
    "intervals",
}
_SCORING = {"boost", "function_score", "dis_max", "boosting", "constant_score", "script_score"}
_TOPOLOGY = {"nested", "has_child", "has_parent", "parent_id", "percolate", "join"}


class DSLError(ValueError):
    """Raised when a query is malformed or uses an unsupported construct."""


def parse_dsl(payload: str | dict[str, Any]) -> Node:
    """Parse Query DSL into the filter AST.

    Accepts either a full search body (``{"query": {...}}``) or a bare query clause
    (``{"term": {...}}``) — both are shapes a user or agent will realistically paste.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DSLError(f"query is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DSLError(f"query must be a JSON object, got {type(payload).__name__}")

    if "query" in payload:
        extra = sorted(set(payload) - _BODY_KEYS)
        if extra:
            raise DSLError(
                f"unsupported search-body key(s): {', '.join(extra)} — "
                "vmctl accepts only `query` (no size/sort/aggs/_source)"
            )
        payload = payload["query"]
        if not isinstance(payload, dict):
            raise DSLError("`query` must be a JSON object")
    return _clause(payload)


def _clause(node: Any) -> Node:
    if not isinstance(node, dict):
        raise DSLError(f"expected a query clause object, got {type(node).__name__}")
    if len(node) != 1:
        raise DSLError(
            f"a query clause must have exactly one key, got {len(node)}: {sorted(node)}"
        )
    (name, body), = node.items()
    handler = _HANDLERS.get(name)
    if handler is None:
        _reject(name)
    return handler(body)


def _reject(name: str) -> NoReturn:
    if name in _FULLTEXT:
        raise DSLError(
            f"`{name}` is not supported: it performs analyzed full-text matching, and "
            "vmctl has no analyzer or field mappings. Use `term`, `wildcard` or `prefix` "
            "for exact matching."
        )
    if name in _SCORING:
        raise DSLError(f"`{name}` is not supported: vmctl filters but does not score.")
    if name in _TOPOLOGY:
        raise DSLError(f"`{name}` is not supported: vmctl has no index topology.")
    raise DSLError(f"unsupported query clause: `{name}`")


def _bool(body: Any) -> Node:
    body = _object("bool", body)
    unknown = sorted(set(body) - {"filter", "must", "must_not", "should", "minimum_should_match"})
    if unknown:
        raise DSLError(f"unsupported `bool` key(s): {', '.join(unknown)}")

    clauses: list[Node] = []
    # `filter` and `must` differ only in scoring, which vmctl does not do — both AND.
    for key in ("filter", "must"):
        clauses.extend(_clause(c) for c in _clause_list(body.get(key)))
    must_not = [_clause(c) for c in _clause_list(body.get("must_not"))]
    clauses.extend(Not(c) for c in must_not)

    should = [_clause(c) for c in _clause_list(body.get("should"))]
    if should and _should_is_required(body):
        clauses.append(Or(tuple(should)))

    if not clauses:
        return MATCH_ALL
    return clauses[0] if len(clauses) == 1 else And(tuple(clauses))


def _should_is_required(body: dict[str, Any]) -> bool:
    """Elasticsearch: `should` defaults to requiring one match when the bool has no
    `must`/`filter`, and to being purely score-affecting (i.e. optional) when it does.
    With no scoring, an optional `should` contributes nothing."""
    msm = body.get("minimum_should_match")
    if msm is None:
        return not (body.get("must") or body.get("filter"))
    if msm in (0, "0"):
        return False
    if msm in (1, "1"):
        return True
    raise DSLError(
        f"unsupported `minimum_should_match`: {msm!r} — only 0 or 1 can be expressed "
        "as a boolean filter"
    )


def _term(body: Any) -> Node:
    field, value = _single_field("term", body)
    return Match(field, ":", _literal(_unwrap(value, "value")))


def _terms(body: Any) -> Node:
    field, values = _single_field("terms", body)
    if not isinstance(values, list):
        raise DSLError("`terms` requires a list of values")
    if not values:
        return Or(())  # matches nothing, as in Elasticsearch
    return Or(tuple(Match(field, ":", _literal(v)) for v in values))


def _range(body: Any) -> Node:
    field, spec = _single_field("range", body)
    spec = _object("range", spec)
    unknown = sorted(set(spec) - set(_RANGE_OPS))
    if unknown:
        raise DSLError(
            f"unsupported `range` option(s): {', '.join(unknown)} — "
            "only gte/gt/lte/lt (absolute ISO-8601, no date math)"
        )
    bounds = [Match(field, _RANGE_OPS[k], _bound(v)) for k, v in spec.items()]
    if not bounds:
        raise DSLError("`range` needs at least one of gte/gt/lte/lt")
    return bounds[0] if len(bounds) == 1 else And(tuple(bounds))


def _exists(body: Any) -> Node:
    body = _object("exists", body)
    field = body.get("field")
    if not isinstance(field, str):
        raise DSLError("`exists` requires a string `field`")
    return Match(field, ":", "*")


def _wildcard(body: Any) -> Node:
    field, value = _single_field("wildcard", body)
    return Match(field, ":", str(_unwrap(value, "value")))


def _prefix(body: Any) -> Node:
    field, value = _single_field("prefix", body)
    text = str(_unwrap(value, "value"))
    if "*" in text or "?" in text:
        # Appending `*` would reinterpret those as wildcards, silently widening the
        # match — and tier 3 has to be exact.
        raise DSLError(f"`prefix` value may not contain * or ?: {text!r}")
    return Match(field, ":", f"{text}*")


def _match_all(body: Any) -> Node:
    _object("match_all", body)
    return MATCH_ALL


_HANDLERS = {
    "bool": _bool,
    "term": _term,
    "terms": _terms,
    "range": _range,
    "exists": _exists,
    "wildcard": _wildcard,
    "prefix": _prefix,
    "match_all": _match_all,
}


def _object(name: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise DSLError(f"`{name}` requires an object, got {type(body).__name__}")
    return body


def _clause_list(value: Any) -> list[Any]:
    """Elasticsearch accepts a single clause or a list of them."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _single_field(name: str, body: Any) -> tuple[str, Any]:
    body = _object(name, body)
    if len(body) != 1:
        raise DSLError(f"`{name}` takes exactly one field, got {sorted(body)}")
    (field, value), = body.items()
    return field, value


def _unwrap(value: Any, key: str) -> Any:
    """Both `{"term": {"f": "v"}}` and `{"term": {"f": {"value": "v"}}}` are valid."""
    if isinstance(value, dict):
        if key not in value:
            raise DSLError(f"expected a `{key}` key, got {sorted(value)}")
        return value[key]
    return value


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        raise DSLError(f"expected a scalar value, got {type(value).__name__}")
    return str(value)


def _bound(value: Any) -> str:
    text = _literal(value)
    if _DATE_MATH.search(text):
        raise DSLError(
            f"date math is not supported: {text!r} — use an absolute ISO-8601 timestamp"
        )
    return text
