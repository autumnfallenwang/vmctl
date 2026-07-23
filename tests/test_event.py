"""Tests for the ECS envelope builder (put fields only; parse/merge is track C)."""

from __future__ import annotations

from datetime import datetime, timezone

from vmctl import __version__
from vmctl.codecs import Frame
from vmctl.config import Filter
from vmctl.event import (
    ECS_VERSION,
    JSON_PARSE_FAILURE,
    build_event,
    enrich,
    event_tags,
    raw_line,
)

NOW = datetime(2026, 7, 23, 0, 4, 42, tzinfo=timezone.utc)


def _put_event(frame: Frame, dataset: str = "ig-audit", file_path: str = "/a.json") -> dict:
    return build_event(
        frame, host="ig1", profile="test_ig", dataset=dataset, file_path=file_path, now=NOW
    )


def test_build_event_put_fields() -> None:
    event = build_event(
        Frame(raw="hello"),
        host="ig1",
        profile="test_ig",
        dataset="ig-route",
        file_path="/opt/ig-instance/logs/route-00-proxy.log",
        now=NOW,
    )
    assert event["@timestamp"] == NOW.isoformat()
    assert event["message"] == "hello"  # unparsed record -> message
    assert event["event"] == {"dataset": "ig-route", "created": NOW.isoformat()}
    assert event["host"] == {"name": "ig1"}
    assert event["agent"] == {"type": "vmctl", "version": __version__}
    assert event["log"] == {"file": {"path": "/opt/ig-instance/logs/route-00-proxy.log"}}
    assert event["labels"] == {"profile": "test_ig"}
    assert event["ecs"] == {"version": ECS_VERSION}


def test_message_equals_raw_including_multiline() -> None:
    raw = "line1\nline2\nline3"
    event = build_event(
        Frame(raw=raw), host="ig2", profile="p", dataset="ig-system", file_path="/x.log", now=NOW
    )
    assert event["message"] == raw
    assert "original" not in event["event"]  # text record: message only


def test_parsed_record_uses_event_original_not_message() -> None:
    """ADR 0004 amendment: the raw line has exactly one home, never both."""
    raw = '{"a":1}'
    event = build_event(
        Frame(raw=raw, parsed={"a": 1}),
        host="ig1",
        profile="p",
        dataset="ig-audit",
        file_path="/a.json",
        now=NOW,
    )
    assert event["event"]["original"] == raw
    assert "message" not in event


def test_tags_emitted_and_json_failure_tagged() -> None:
    good = Frame(raw='{"a":1}', parsed={"a": 1})
    bad = Frame(raw='{"a":', parsed=None)
    assert event_tags(good, codec_name="json", configured=["prod"]) == ["prod"]
    assert event_tags(bad, codec_name="json") == [JSON_PARSE_FAILURE]
    assert event_tags(bad, codec_name="json", configured=["prod"]) == ["prod", JSON_PARSE_FAILURE]
    # A text record is not a parse failure — message is simply its content.
    assert event_tags(bad, codec_name="multiline") == []

    event = build_event(
        bad, host="h", profile="p", dataset="ig-audit", file_path="/a.json", now=NOW,
        tags=event_tags(bad, codec_name="json"),
    )
    assert event["tags"] == [JSON_PARSE_FAILURE]
    assert event["message"] == '{"a":'  # raw kept so the bad line is still inspectable


def test_no_tags_key_when_empty() -> None:
    event = build_event(
        Frame(raw="x"), host="h", profile="p", dataset="d", file_path="/x", now=NOW
    )
    assert "tags" not in event


def test_dataset_from_input_type() -> None:
    event = build_event(
        Frame(raw="{}"), host="h", profile="p", dataset="ig-audit", file_path="/a.json", now=NOW
    )
    assert event["event"]["dataset"] == "ig-audit"


def test_enrich_merges_json_and_protects_envelope() -> None:
    parsed = {
        "transactionId": "t-1",
        "http": {"request": {"method": "GET"}},
        "host": "SHOULD-NOT-CLOBBER",  # reserved envelope key
    }
    frame = Frame(raw='{"transactionId":"t-1"}', parsed=parsed)
    event = enrich(_put_event(frame), frame, filters=[], file_path="/a.json")
    assert event["transactionId"] == "t-1"
    assert event["http"]["request"]["method"] == "GET"
    assert event["host"] == {"name": "ig1"}  # envelope host wins over merged json


def test_enrich_timestamp_from_json_field() -> None:
    parsed = {"timestamp": "2026-07-23T00:04:54.741Z", "ig": {"routeId": "00-proxy"}}
    frame = Frame(raw="{}", parsed=parsed)
    event = enrich(_put_event(frame), frame, filters=[], file_path="/a.json")
    assert event["@timestamp"].startswith("2026-07-23T00:04:54.741")
    assert event["@timestamp"] != NOW.isoformat()  # log time, not collection time
    assert event["labels"]["route_id"] == "00-proxy"  # ig.routeId mirrored


def test_enrich_timestamp_from_text_message() -> None:
    frame = Frame(raw="2026-07-23T00:04:42,571Z | INFO | ... @00-proxy | hi")  # comma millis
    event = enrich(
        _put_event(frame, dataset="ig-system", file_path="/route-system.log"),
        frame,
        filters=[],
        file_path="/route-system.log",
    )
    assert event["@timestamp"].startswith("2026-07-23T00:04:42.571")


def test_raw_line_reads_either_home() -> None:
    assert raw_line({"message": "text line"}) == "text line"
    assert raw_line({"event": {"original": '{"a":1}'}}) == '{"a":1}'
    assert raw_line({}) == ""


def test_enrich_timestamp_from_parsed_records_raw_line() -> None:
    """A parsed record with no `timestamp` field still gets its time from the raw
    line — which now lives in event.original rather than message."""
    frame = Frame(raw="2026-07-23T00:04:42,571Z {...}", parsed={"level": "INFO"})
    event = enrich(_put_event(frame), frame, filters=[], file_path="/a.json")
    assert event["@timestamp"].startswith("2026-07-23T00:04:42.571")


def test_enrich_route_id_from_filename_grok() -> None:
    frame = Frame(raw="2026-07-23T00:00:00,000Z | INFO | @00-proxy | x")
    filters = [
        Filter(condition='[type] == "ig-route"', grok={"path": r"route-%{DATA:route_id}\.log"})
    ]
    event = enrich(
        _put_event(frame, dataset="ig-route", file_path="/logs/route-00-proxy.log"),
        frame,
        filters=filters,
        file_path="/logs/route-00-proxy.log",
    )
    assert event["labels"]["route_id"] == "00-proxy"
