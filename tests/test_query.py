"""Tier-3 evaluator tests — exact matching over ECS events (docs/adr/0005, 0007)."""

from __future__ import annotations

from typing import Any

from dslq import all_of, any_of, exists, none_of, q, rng, term, wildcard

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


def _m(clause: dict[str, Any], event: dict[str, Any] | None = None) -> bool:
    return matches(q(clause), event if event is not None else _event())


def test_term_equality_string_and_number() -> None:
    assert _m(term("event.dataset", "ig-audit"))
    assert not _m(term("event.dataset", "ig-route"))
    assert _m(term("host.name", "192.168.77.11"))
    # statusCode is stored as a string; a numeric query value still matches it.
    assert _m(term("response.statusCode", 500))
    assert not _m(term("response.statusCode", 200))
    # A genuinely numeric field compares numerically too.
    assert _m(term("response.elapsedTime", 4))
    # Booleans compare as words, not as 1/0.
    assert _m(term("ok", True), _event(ok=True))
    assert not _m(term("ok", 1), _event(ok=True))


def test_missing_field_false() -> None:
    assert not _m(term("foo.bar", "anything"))
    assert _m(none_of(term("foo.bar", "anything")))
    # An explicit null is treated the same as absent.
    assert not _m(exists("labels.route_id"), _event(labels={"route_id": None}))


def test_exists() -> None:
    assert _m(exists("labels.route_id"))
    assert _m(exists("response.statusCode"))
    assert not _m(exists("labels.nope"))


def test_wildcard() -> None:
    assert _m(wildcard("labels.route_id", "00-*"))
    assert not _m(wildcard("labels.route_id", "01-*"))
    assert _m(wildcard("message", "*9080*"))
    assert _m(wildcard("labels.route_id", "00-prox?"))
    assert _m({"prefix": {"labels.route_id": "00-"}})


def test_range_numeric() -> None:
    # The field is the string "500" — a numeric bound still compares as a number.
    assert _m(rng("response.statusCode", gte=500))
    assert not _m(rng("response.statusCode", gt=500))
    assert _m(rng("response.statusCode", lt=501))
    assert not _m(rng("response.statusCode", lte=499))


def test_range_timestamp_compares_as_instants() -> None:
    assert _m(rng("@timestamp", gte="2026-07-23T00:00:00"))
    assert not _m(rng("@timestamp", lt="2026-07-23T00:00:00"))
    # Tier 3 is exact: a bound written with `Z` and an event written with `+00:00`
    # order correctly, and a same-second bound includes the event rather than
    # falling foul of string length. The *remote* pass stays lexicographic — it only
    # has to be a superset.
    assert _m(rng("@timestamp", lte="2026-07-23T00:04:42.571Z"))
    assert _m(rng("@timestamp", lte="2026-07-23T00:04:43"))
    assert not _m(rng("@timestamp", lte="2026-07-23T00:04:42"))  # strictly earlier instant
    # A date-only bound still orders sensibly against a full timestamp.
    assert _m(rng("@timestamp", lte="2026-07-24"))


def test_boolean_and_or_not() -> None:
    assert _m(all_of(term("event.dataset", "ig-audit"), rng("response.statusCode", gte=500)))
    assert not _m(all_of(term("event.dataset", "ig-audit"), rng("response.statusCode", lt=500)))
    assert _m(any_of(term("event.dataset", "nope"), term("labels.route_id", "00-proxy")))
    assert _m(none_of(term("event.dataset", "nope")))
    assert not _m(
        all_of(
            any_of(term("event.dataset", "nope"), term("labels.route_id", "zzz")),
            term("response.statusCode", 500),
        )
    )


def test_multi_valued_field_matches_any_element() -> None:
    """Elasticsearch indexes every element of an array under the same field, so a
    predicate matches if any element does. IG's audit headers are arrays, so without
    this a header query silently returns nothing."""
    event = _event(http={"request": {"headers": {"host": ["ig1:9080", "alt:9080"]}}})
    assert _m(term("http.request.headers.host", "ig1:9080"), event)
    assert _m(term("http.request.headers.host", "alt:9080"), event)
    assert not _m(term("http.request.headers.host", "nope:9080"), event)
    assert _m(wildcard("http.request.headers.host", "ig1*"), event)
    assert _m(exists("http.request.headers.host"), event)
    # Ranges too.
    assert _m(rng("codes", gte=400), _event(codes=[200, 503]))
    assert not _m(rng("codes", gte=600), _event(codes=[200, 503]))


def test_empty_array_does_not_exist() -> None:
    """An empty array indexes no value, so Elasticsearch reports the field absent."""
    assert not _m(exists("tags"), _event(tags=[]))
    assert not _m(exists("tags"), _event(tags=[None]))
    assert _m(exists("tags"), _event(tags=["a"]))


def test_terms_matches_any_value() -> None:
    assert _m({"terms": {"response.statusCode": ["500", "503"]}})
    assert not _m({"terms": {"response.statusCode": ["200", "201"]}})


def test_match_all() -> None:
    assert _m({"match_all": {}})


def test_resolve_nested_and_flat_dotted() -> None:
    nested = _event()
    flat: dict[str, Any] = {"response.statusCode": "500", "event": {"dataset": "ig-audit"}}
    assert resolve_field(nested, "response.statusCode") == "500"
    assert resolve_field(flat, "response.statusCode") == "500"
    assert resolve_field(nested, "response.missing") is None
    # Descending into a non-dict must not raise.
    assert resolve_field(nested, "message.nope") is None
    assert _m(term("response.statusCode", 500), flat)
