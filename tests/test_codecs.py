"""Tests for the framing codecs (fixture-driven, no network)."""

from __future__ import annotations

from vmctl.codecs import (
    JsonCodec,
    MultilineCodec,
    PlainCodec,
    frame_lines,
    make_codec,
)
from vmctl.config import Codec

TS = r"^\d{4}-\d{2}-\d{2}T"

# A real IG-shaped route-capture block: one event, timestamp line + [CONTINUED] lines.
ROUTE_LINES = [
    "2026-07-23T00:04:42,571Z | INFO | ... @00-proxy |",
    "[CONTINUED]--- (request) exchangeId:e24... --->",
    "[CONTINUED]GET http://127.0.0.1:9080/ HTTP/1.1",
    "2026-07-23T00:04:42,668Z | INFO | ... @00-proxy |",
    "[CONTINUED]<--- (response) ... ---",
]


def test_plain_one_frame_per_line() -> None:
    frames = list(frame_lines(PlainCodec(), ["a", "b", "c"]))
    assert [f.raw for f in frames] == ["a", "b", "c"]
    assert all(f.parsed is None for f in frames)


def test_json_parses_line() -> None:
    frames = list(frame_lines(JsonCodec(), ['{"a": 1, "b": {"c": 2}}']))
    assert len(frames) == 1
    assert frames[0].parsed == {"a": 1, "b": {"c": 2}}


def test_json_broken_line_graceful() -> None:
    frames = list(frame_lines(JsonCodec(), ['{"a": 1', "not json at all"]))
    assert [f.parsed for f in frames] == [None, None]
    assert frames[0].raw == '{"a": 1'  # raw preserved for the envelope's message


def test_multiline_previous_keeps_events_whole() -> None:
    codec = MultilineCodec(TS, negate=True, what="previous")
    frames = list(frame_lines(codec, ROUTE_LINES))
    assert len(frames) == 2  # two timestamp-anchored events
    assert frames[0].raw.startswith("2026-07-23T00:04:42,571Z")
    assert "GET http://127.0.0.1:9080/" in frames[0].raw  # continuation lines joined in
    assert frames[1].raw.startswith("2026-07-23T00:04:42,668Z")
    assert "response" in frames[1].raw


def test_multiline_next() -> None:
    # A line ending in '\' continues to the next; the following line closes the event.
    codec = MultilineCodec(r"\\$", negate=False, what="next")
    frames = list(frame_lines(codec, ["a \\", "b", "c \\", "d"]))
    assert [f.raw for f in frames] == ["a \\\nb", "c \\\nd"]


def test_make_codec_from_config() -> None:
    assert isinstance(make_codec(Codec(name="plain")), PlainCodec)
    assert isinstance(make_codec(Codec(name="json")), JsonCodec)
    ml = make_codec(Codec(name="multiline", pattern=TS, negate=True, what="previous"))
    assert isinstance(ml, MultilineCodec)
