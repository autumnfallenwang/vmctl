"""Tests for the output sinks."""

from __future__ import annotations

import json

from vmctl.output import to_human, to_ndjson

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


def test_to_human_summary() -> None:
    line = to_human(EVENT)
    assert "ig1" in line
    assert "ig-route[00-proxy]" in line
    assert "hello" in line and "second line" not in line  # first line only
