"""Parser tests for the KQL subset (docs/adr/0005, track A)."""

from __future__ import annotations

import pytest

from vmctl.kql import And, KQLError, Match, Not, Or, parse


def test_parse_simple_term() -> None:
    assert parse("event.dataset:ig-audit") == Match("event.dataset", ":", "ig-audit")


def test_parse_quoted_value() -> None:
    assert parse('message:"hello world"') == Match("message", ":", "hello world")
    assert parse("message:'single quoted'") == Match("message", ":", "single quoted")


def test_parse_and_or_precedence() -> None:
    # `and` binds tighter than `or`.
    assert parse("a:1 or b:2 and c:3") == Or(
        (Match("a", ":", "1"), And((Match("b", ":", "2"), Match("c", ":", "3"))))
    )


def test_parse_not() -> None:
    assert parse("not a:1") == Not(Match("a", ":", "1"))
    assert parse("a:1 and not b:2") == And((Match("a", ":", "1"), Not(Match("b", ":", "2"))))


def test_parse_parentheses() -> None:
    assert parse("(a:1 or b:2) and c:3") == And(
        (Or((Match("a", ":", "1"), Match("b", ":", "2"))), Match("c", ":", "3"))
    )


def test_parse_ranges() -> None:
    assert parse('@timestamp >= "2026-07-23T00:00:00Z"') == Match(
        "@timestamp", ">=", "2026-07-23T00:00:00Z"
    )
    # Spaces around the operator are optional.
    assert parse("code>=500") == Match("code", ">=", "500")
    assert parse("code<500") == Match("code", "<", "500")
    assert parse("code <= 500") == Match("code", "<=", "500")
    assert parse("code > 500") == Match("code", ">", "500")


def test_parse_wildcard_and_exists() -> None:
    assert parse("labels.route_id:00-*") == Match("labels.route_id", ":", "00-*")
    assert parse("http.response.statusCode:*") == Match("http.response.statusCode", ":", "*")


def test_parse_case_insensitive_keywords() -> None:
    assert parse("A:1 AND B:2") == And((Match("A", ":", "1"), Match("B", ":", "2")))
    assert parse("a:1 OR b:2") == Or((Match("a", ":", "1"), Match("b", ":", "2")))
    assert parse("NOT a:1") == Not(Match("a", ":", "1"))


def test_parse_value_keyword() -> None:
    # After an operator the next token is a value, even if it spells a keyword.
    assert parse("status:not") == Match("status", ":", "not")
    assert parse("status:and and b:2") == And((Match("status", ":", "and"), Match("b", ":", "2")))


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "a:",  # dangling operator
        "a",  # no operator
        "(a:1",  # unbalanced paren
        "a:1)",  # trailing input
        "a:1 and",  # dangling connective
        "and a:1",  # leading keyword where a field belongs
        'a:"unterminated',
    ],
)
def test_parse_errors(query: str) -> None:
    with pytest.raises(KQLError):
        parse(query)
