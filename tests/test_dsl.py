"""Query DSL front end — the sole query input (docs/adr/0007)."""

from __future__ import annotations

import pytest

from vmctl.predicate import MATCH_ALL, And, Match, Not, Or
from vmctl.dsl import DSLError, parse_dsl


def test_accepts_full_body_and_bare_clause() -> None:
    bare = {"term": {"event.dataset": "ig-audit"}}
    assert parse_dsl(bare) == Match("event.dataset", ":", "ig-audit")
    assert parse_dsl({"query": bare}) == Match("event.dataset", ":", "ig-audit")
    assert parse_dsl('{"term": {"event.dataset": "ig-audit"}}') == Match(
        "event.dataset", ":", "ig-audit"
    )


def test_term_long_form_and_scalar_types() -> None:
    assert parse_dsl({"term": {"f": {"value": "x"}}}) == Match("f", ":", "x")
    assert parse_dsl({"term": {"f": 500}}) == Match("f", ":", "500")
    assert parse_dsl({"term": {"f": True}}) == Match("f", ":", "true")


def test_terms_is_an_or() -> None:
    assert parse_dsl({"terms": {"code": ["500", "503"]}}) == Or(
        (Match("code", ":", "500"), Match("code", ":", "503"))
    )
    assert parse_dsl({"terms": {"code": []}}) == Or(())  # matches nothing, as in ES


def test_range_single_and_double_bound() -> None:
    assert parse_dsl({"range": {"n": {"gte": 5}}}) == Match("n", ">=", "5")
    assert parse_dsl({"range": {"@timestamp": {"gte": "2026-07-23", "lt": "2026-07-24"}}}) == And(
        (Match("@timestamp", ">=", "2026-07-23"), Match("@timestamp", "<", "2026-07-24"))
    )


def test_exists_wildcard_prefix_match_all() -> None:
    assert parse_dsl({"exists": {"field": "ig.routeId"}}) == Match("ig.routeId", ":", "*")
    assert parse_dsl({"wildcard": {"r": "00-*"}}) == Match("r", ":", "00-*")
    assert parse_dsl({"prefix": {"r": "00-"}}) == Match("r", ":", "00-*")
    assert parse_dsl({"match_all": {}}) == MATCH_ALL


def test_bool_filter_must_must_not() -> None:
    node = parse_dsl(
        {
            "bool": {
                "filter": [{"term": {"a": "1"}}],
                "must": [{"term": {"b": "2"}}],
                "must_not": [{"term": {"c": "3"}}],
            }
        }
    )
    # filter and must are both AND — they differ only in scoring, which vmctl lacks.
    assert node == And(
        (Match("a", ":", "1"), Match("b", ":", "2"), Not(Match("c", ":", "3")))
    )


def test_bool_accepts_single_clause_not_only_lists() -> None:
    assert parse_dsl({"bool": {"filter": {"term": {"a": "1"}}}}) == Match("a", ":", "1")


def test_should_semantics_follow_elasticsearch() -> None:
    # No must/filter -> should is required (minimum_should_match defaults to 1).
    assert parse_dsl({"bool": {"should": [{"term": {"a": "1"}}, {"term": {"b": "2"}}]}}) == Or(
        (Match("a", ":", "1"), Match("b", ":", "2"))
    )
    # With a filter present, should defaults to score-only — and vmctl does not score,
    # so it contributes nothing.
    assert parse_dsl(
        {"bool": {"filter": [{"term": {"a": "1"}}], "should": [{"term": {"b": "2"}}]}}
    ) == Match("a", ":", "1")
    # ...unless explicitly required.
    assert parse_dsl(
        {
            "bool": {
                "filter": [{"term": {"a": "1"}}],
                "should": [{"term": {"b": "2"}}],
                "minimum_should_match": 1,
            }
        }
    ) == And((Match("a", ":", "1"), Or((Match("b", ":", "2"),))))


def test_empty_bool_is_match_all() -> None:
    assert parse_dsl({"bool": {}}) == MATCH_ALL


def test_nested_bool() -> None:
    node = parse_dsl(
        {
            "bool": {
                "filter": [
                    {"term": {"event.dataset": "ig-audit"}},
                    {"bool": {"should": [{"term": {"c": "500"}}, {"term": {"c": "503"}}]}},
                ]
            }
        }
    )
    assert node == And(
        (
            Match("event.dataset", ":", "ig-audit"),
            Or((Match("c", ":", "500"), Match("c", ":", "503"))),
        )
    )


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ({"match": {"message": "error"}}, "analyzed"),
        ({"match_phrase": {"message": "a b"}}, "analyzed"),
        ({"multi_match": {"query": "x"}}, "analyzed"),
        ({"query_string": {"query": "x"}}, "analyzed"),
        ({"function_score": {}}, "does not score"),
        ({"constant_score": {}}, "does not score"),
        ({"nested": {}}, "index topology"),
        ({"has_child": {}}, "index topology"),
        ({"fuzzy": {"f": "x"}}, "unsupported query clause"),
    ],
)
def test_unsupported_constructs_raise_with_a_reason(clause: dict, expected: str) -> None:
    """Never a silent no-op: a filter that quietly matched everything would return
    plausible-looking wrong results."""
    with pytest.raises(DSLError, match=expected):
        parse_dsl(clause)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"query": {"term": {"a": "1"}}, "size": 10}, "size"),
        ({"query": {"term": {"a": "1"}}, "sort": []}, "sort"),
        ({"query": {"term": {"a": "1"}}, "aggs": {}}, "aggs"),
    ],
)
def test_search_body_extras_are_rejected(payload: dict, expected: str) -> None:
    # Silently dropping `size: 10` would badly mislead about what was returned.
    with pytest.raises(DSLError, match=expected):
        parse_dsl(payload)


@pytest.mark.parametrize(
    "value", ["now-1d", "now", "now-1d/d", "2020||+1M"]
)
def test_date_math_is_rejected(value: str) -> None:
    with pytest.raises(DSLError, match="date math"):
        parse_dsl({"range": {"@timestamp": {"gte": value}}})


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("not json at all", "not valid JSON"),
        ("[1,2]", "must be a JSON object"),
        ({"term": {"a": "1"}, "range": {"b": {"gte": 1}}}, "exactly one key"),
        ({"term": {"a": "1", "b": "2"}}, "exactly one field"),
        ({"range": {"f": {}}}, "at least one"),
        ({"range": {"f": {"between": 1}}}, "unsupported `range` option"),
        ({"exists": {}}, "requires a string `field`"),
        ({"bool": {"filter": [], "boost": 2}}, "unsupported `bool` key"),
        ({"bool": {"should": [{"term": {"a": "1"}}], "minimum_should_match": 2}}, "minimum_should"),
        ({"prefix": {"f": "a*b"}}, r"may not contain"),
    ],
)
def test_malformed_queries_raise(payload: object, expected: str) -> None:
    with pytest.raises(DSLError, match=expected):
        parse_dsl(payload)  # type: ignore[arg-type]
