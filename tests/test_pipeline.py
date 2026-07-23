"""End-to-end framing → ECS pipeline over the real captured corpus (M03 flagship).

Proves all three test-env log shapes produce correct ECS events, plus graceful
handling of a broken JSON line.
"""

from __future__ import annotations

from pathlib import Path

from vmctl.codecs import frame_lines, make_codec
from vmctl.config import Input, Profile, load_config
from vmctl.event import assemble

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "testenv" / "infra" / "vmctl.example.yml"
CORPUS = ROOT / "testenv" / "corpus"


def _profile() -> Profile:
    return load_config(EXAMPLE).profiles["test_ig"]


def _input(profile: Profile, dataset: str) -> Input:
    return next(i for i in profile.inputs if i.type == dataset)


def _events(profile: Profile, dataset: str, corpus_file: str, file_path: str) -> list[dict]:
    inp = _input(profile, dataset)
    lines = (CORPUS / corpus_file).read_text().splitlines()
    return [
        assemble(
            f, host="ig1", profile="test_ig", inp=inp, file_path=file_path, filters=profile.filters
        )
        for f in frame_lines(make_codec(inp.codec), lines)
    ]


def test_audit_shape() -> None:
    events = _events(
        _profile(),
        "ig-audit",
        "audit-access.jsonl",
        "/opt/ig-instance/logs/audit/access.audit.json",
    )
    assert events, "no audit events"
    e = events[0]
    assert e["event"]["dataset"] == "ig-audit"
    assert e["host"]["name"] == "ig1"
    assert e["@timestamp"].startswith("2026-07-23T00:04")  # parsed from the json timestamp field
    assert e["labels"]["route_id"] == "00-proxy"  # mirrored from ig.routeId
    assert "transactionId" in e  # merged json field


def test_route_capture_shape() -> None:
    events = _events(
        _profile(), "ig-route", "route-capture.log", "/opt/ig-instance/logs/route-00-proxy.log"
    )
    assert events, "no route events"
    e = events[0]
    assert e["event"]["dataset"] == "ig-route"
    assert e["@timestamp"].startswith("2026-07-23T")  # parsed from the leading text timestamp
    assert e["labels"]["route_id"] == "00-proxy"  # from the filename grok
    assert "GET http://127.0.0.1:9080/" in e["message"]  # multiline event kept whole


def test_system_shape_has_no_route() -> None:
    events = _events(
        _profile(), "ig-system", "route-system.log", "/opt/ig-instance/logs/route-system.log"
    )
    assert events
    e = events[0]
    assert e["event"]["dataset"] == "ig-system"
    assert e["@timestamp"].startswith("2026-07-23T")
    assert e["labels"] == {"profile": "test_ig"}  # system has no route


def test_broken_json_is_graceful() -> None:
    events = _events(_profile(), "ig-audit", "broken.jsonl", "/opt/ig-instance/logs/audit/x.json")
    assert len(events) == 3
    assert events[0]["labels"]["route_id"] == "good"  # first line parsed + merged
    assert events[2]["labels"]["route_id"] == "fine"  # third line parsed + merged
    # the middle line was not valid JSON — no merge, but no crash and message preserved
    assert "route_id" not in events[1]["labels"]
    assert events[1]["message"].startswith('{"_id":"b"')
