"""Tests for the output sinks."""

from __future__ import annotations

import json

from vmctl.output import to_ndjson

EVENT = {
    "@timestamp": "2026-07-23T00:04:54.741000+00:00",
    "message": "hello\nsecond line",
    "event": {"dataset": "ig-route"},
    "host": {"name": "ig1"},
    "labels": {"profile": "test_ig", "route_id": "00-proxy"},
}


def test_to_ndjson_roundtrips() -> None:
    line = to_ndjson(EVENT)
    assert "\n" not in line  # single line
    assert json.loads(line) == EVENT


def test_ndjson_is_the_only_sink() -> None:
    """ADR 0007: no human rendering to drift out of step with the record."""
    import vmctl.output as output

    assert not hasattr(output, "to_human")
