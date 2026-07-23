"""Tier-3 evaluator tests — exact KQL matching over ECS events (docs/adr/0005, track B)."""

from __future__ import annotations

from typing import Any

from vmctl.kql import parse
from vmctl.query import matches, resolve_field


def _event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "@timestamp": "2026-07-23T00:04:42.571000+00:00",
        "message": "GET http://127.0.0.1:9080/ HTTP/1.1",
        "event": {"dataset": "ig-audit"},
        "host": {"name": "192.168.77.11"},
        "labels": {"profile": "test_ig", "route_id": "00-proxy"},
        # Mirrors the real IG audit shape: `http` holds only the request, `response` is
        # top-level, and statusCode is a *string* — which must still compare numerically.
        "http": {"request": {"method": "GET"}},
        "response": {"status": "SERVER_ERROR", "statusCode": "500", "elapsedTime": 4},
    }
    event.update(overrides)
    return event


def _m(query: str, event: dict[str, Any] | None = None) -> bool:
    return matches(parse(query), event if event is not None else _event())


def test_term_equality_string_and_number() -> None:
    assert _m("event.dataset:ig-audit")
    assert not _m("event.dataset:ig-route")
    assert _m("host.name:192.168.77.11")
    # statusCode is stored as a string; a numeric-looking query still matches it.
    assert _m("response.statusCode:500")
    assert not _m("response.statusCode:200")
    # A genuinely numeric field compares numerically too.
    assert _m("response.elapsedTime:4")
    # Booleans compare as words, not as 1/0.
    assert _m("ok:true", _event(ok=True))
    assert not _m("ok:1", _event(ok=True))


def test_missing_field_false() -> None:
    assert not _m("foo.bar:anything")
    assert _m("not foo.bar:anything")
    # An explicit null is treated the same as absent.
    assert not _m("labels.route_id:*", _event(labels={"route_id": None}))


def test_exists() -> None:
    assert _m("labels.route_id:*")
    assert _m("response.statusCode:*")
    assert not _m("labels.nope:*")


def test_wildcard() -> None:
    assert _m("labels.route_id:00-*")
    assert not _m("labels.route_id:01-*")
    assert _m("message:*9080*")
    assert _m("labels.route_id:00-prox?")


def test_range_numeric() -> None:
    # The field is the string "500" — a numeric bound still compares as a number.
    assert _m("response.statusCode >= 500")
    assert not _m("response.statusCode > 500")
    assert _m("response.statusCode < 501")
    assert not _m("response.statusCode <= 499")


def test_range_timestamp_lexicographic() -> None:
    # Uniform UTC ISO sorts lexicographically — no date math (ADR 0005).
    assert _m('@timestamp >= "2026-07-23T00:00:00"')
    assert not _m('@timestamp < "2026-07-23T00:00:00"')
    assert _m('@timestamp <= "2026-07-24"')
    # A *truncated* upper bound excludes a same-second match, because the event
    # string is longer than the bound — the exact reason tier-2 pushdown must widen
    # its window outward rather than compare on a truncated prefix.
    assert not _m('@timestamp <= "2026-07-23T00:04:42"')


def test_boolean_and_or_not() -> None:
    assert _m("event.dataset:ig-audit and response.statusCode >= 500")
    assert not _m("event.dataset:ig-audit and response.statusCode < 500")
    assert _m("event.dataset:nope or labels.route_id:00-proxy")
    assert _m("not event.dataset:nope")
    assert not _m("(event.dataset:nope or labels.route_id:zzz) and response.statusCode:500")


def test_resolve_nested_and_flat_dotted() -> None:
    nested = _event()
    flat: dict[str, Any] = {"response.statusCode": "500", "event": {"dataset": "ig-audit"}}
    assert resolve_field(nested, "response.statusCode") == "500"
    assert resolve_field(flat, "response.statusCode") == "500"
    assert resolve_field(nested, "response.missing") is None
    # Descending into a non-dict must not raise.
    assert resolve_field(nested, "message.nope") is None
    assert _m("response.statusCode:500", flat)
