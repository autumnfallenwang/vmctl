"""Tier-2 pushdown tests (docs/adr/0005).

The window tests **execute the generated awk** against real files, so what is verified is
the program's behaviour, not a string comparison against an expected command.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dslq import all_of, any_of, q, term

from vmctl.pushdown import (
    Window,
    bound_to_prefix,
    build_read_command,
    pushable_terms,
    window_from,
    window_from_query,
)

CORPUS = Path(__file__).resolve().parents[1] / "testenv" / "corpus"

needs_awk = pytest.mark.skipif(shutil.which("awk") is None, reason="awk not available")

# Two events, each with a [CONTINUED] body and a *blank* continuation line, in different
# seconds — the corpus's own capture log has both events inside one second, so a
# purpose-built fixture is what actually exercises the carry rule.
MULTILINE_FIXTURE = (
    "\n".join(
        [
            "2026-07-23T00:00:01,100Z | INFO  | @00-proxy | first",
            "[CONTINUED]first body",
            "",
            "[CONTINUED]first tail",
            "2026-07-23T00:00:09,900Z | INFO  | @00-proxy | second",
            "[CONTINUED]second body",
            "",
            "[CONTINUED]second tail",
        ]
    )
    + "\n"
)


def _run(cmd: str) -> list[str]:
    proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False)
    assert proc.returncode in (0, 1), proc.stderr  # grep exits 1 on no match
    return proc.stdout.split("\n")[:-1] if proc.stdout else []


def _text_cmd(path: Path, **kw: str) -> str:
    return build_read_command(str(path), codec_name="multiline", window=Window(**kw))


@needs_awk
def test_text_window_keeps_whole_multiline_event(tmp_path: Path) -> None:
    log = tmp_path / "route-00-proxy.log"
    log.write_text(MULTILINE_FIXTURE, encoding="utf-8")

    later = _run(_text_cmd(log, since="2026-07-23T00:00:05"))
    assert later == [
        "2026-07-23T00:00:09,900Z | INFO  | @00-proxy | second",
        "[CONTINUED]second body",
        "",  # the blank continuation line must survive — it is part of the event
        "[CONTINUED]second tail",
    ]

    earlier = _run(_text_cmd(log, until="2026-07-23T00:00:05"))
    assert earlier == [
        "2026-07-23T00:00:01,100Z | INFO  | @00-proxy | first",
        "[CONTINUED]first body",
        "",
        "[CONTINUED]first tail",
    ]


@needs_awk
def test_text_window_on_real_capture_log() -> None:
    # Comma-millis timestamps, real [CONTINUED] and blank lines: a window covering the
    # events keeps every physical line; one after them keeps none.
    log = CORPUS / "route-capture.log"
    everything = _run(_text_cmd(log, since="2026-07-23T00:00:00"))
    assert everything == log.read_text(encoding="utf-8").split("\n")[:-1]
    assert _run(_text_cmd(log, since="2026-07-24T00:00:00")) == []


@needs_awk
def test_audit_json_window() -> None:
    log = CORPUS / "audit-access.jsonl"
    cmd = build_read_command(
        str(log), codec_name="json", window=Window(since="2026-07-23T00:04:54")
    )
    assert len(_run(cmd)) == 2
    after = build_read_command(
        str(log), codec_name="json", window=Window(since="2026-07-23T00:04:55")
    )
    assert _run(after) == []


@needs_awk
def test_unparseable_line_is_kept() -> None:
    # A truncated timestamp can't be compared, so the line rides along and tier 3 decides.
    cmd = build_read_command(
        str(CORPUS / "broken.jsonl"),
        codec_name="json",
        window=Window(since="2026-07-23T00:00:02"),
    )
    out = "\n".join(_run(cmd))
    assert '"_id":"b"' in out  # truncated timestamp — kept
    assert '"_id":"c"' in out  # inside the window
    assert '"_id":"a"' not in out  # definitively before it


@needs_awk
def test_terms_are_applied_to_json_reads(tmp_path: Path) -> None:
    log = tmp_path / "access.audit.json"
    log.write_text(
        '{"timestamp":"2026-07-23T00:00:01.000Z","response":{"statusCode":"500"}}\n'
        '{"timestamp":"2026-07-23T00:00:02.000Z","response":{"statusCode":"200"}}\n',
        encoding="utf-8",
    )
    cmd = build_read_command(str(log), codec_name="json", window=Window(), terms=["500"])
    out = _run(cmd)
    assert len(out) == 1 and '"500"' in out[0]


def test_no_window_is_cat() -> None:
    assert build_read_command("/logs/x.log", codec_name="plain") == "cat '/logs/x.log'"


def test_bounds_truncated_to_second() -> None:
    at = datetime(2026, 7, 23, 0, 4, 42, 571000, tzinfo=timezone.utc)
    assert bound_to_prefix(at) == "2026-07-23T00:04:42"
    # A naive bound is read as UTC; an offset one is converted.
    assert bound_to_prefix(datetime(2026, 7, 23, 1, 0, 0)) == "2026-07-23T01:00:00"
    assert window_from(at, None) == Window(since="2026-07-23T00:04:42", until=None)
    assert Window().empty and not Window(since="x").empty


def test_terms_only_for_json_codec() -> None:
    query = q(term("response.statusCode", 500))
    assert pushable_terms(query, codec_name="json") == ["500"]
    # A grep would drop the continuation lines of a multi-line event.
    assert pushable_terms(query, codec_name="multiline") == []
    assert pushable_terms(query, codec_name="plain") == []


def test_terms_reject_put_fields_wildcards_and_floats() -> None:
    def terms(clause: dict) -> list[str]:
        return pushable_terms(q(clause), codec_name="json")

    assert terms(term("host.name", "192.168.77.11")) == []  # generated, never in the text
    assert terms(term("event.dataset", "ig-audit")) == []
    assert terms(term("log.file.path", "/logs/a.json")) == []
    assert terms(term("@timestamp", "2026")) == []
    assert terms(term("labels.profile", "test_ig")) == []
    assert terms({"wildcard": {"labels.route_id": "00-*"}}) == []  # not a substring
    assert terms({"exists": {"field": "response.statusCode"}}) == []  # says nothing
    assert terms(term("response.elapsedTime", 500.0)) == []  # could be 5e2 in the file
    assert terms({"range": {"response.statusCode": {"gte": 500}}}) == []  # not a substring


def test_terms_reject_unsafe_values() -> None:
    assert pushable_terms(q(term("a", "it's")), codec_name="json") == []
    assert pushable_terms(q(term("a", "$(rm -rf /)")), codec_name="json") == []


def test_terms_ignore_or_branches() -> None:
    # Neither side of an `or` is required, so neither may be pushed.
    assert pushable_terms(q(any_of(term("a", 1), term("b", 2))), codec_name="json") == []
    assert (
        pushable_terms(
            q(all_of(term("a", 1), any_of(term("b", 2), term("c", 3)))), codec_name="json"
        )
        == ["1"]
    )


def test_window_comes_from_the_query() -> None:
    """A `range` on @timestamp reaches the remote awk — the filter carries its bounds."""
    node = q(
        all_of(
            term("event.dataset", "ig-audit"),
            {"range": {"@timestamp": {"gte": "2026-07-23T14:38:00Z", "lt": "2026-07-23T14:39:00"}}},
        )
    )
    assert window_from_query(node) == Window(
        since="2026-07-23T14:38:00", until="2026-07-23T14:39:00"
    )
    # No @timestamp predicate -> no window, so the whole file is read.
    assert window_from_query(q(term("a", "b"))).empty
    # An `or` cannot narrow: neither branch is required.
    assert window_from_query(
        q(any_of({"range": {"@timestamp": {"gte": "2026-07-23T00:00:00"}}}, term("a", "b")))
    ).empty
    # A bound too coarse to compare against a 19-char prefix is ignored, not guessed at.
    assert window_from_query(q({"range": {"@timestamp": {"gte": "2026-07-23"}}})).empty


def test_refuses_quoted_path() -> None:
    with pytest.raises(ValueError, match="single quote"):
        build_read_command("/logs/it's.log", codec_name="json")
