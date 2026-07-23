"""Fast tests for the tail streaming pipeline (fake transport, no network)."""

from __future__ import annotations

import asyncio

from fakes import FakeConnection, FakeTransport

from vmctl.config import Codec, Filter, Host, Input, Profile
from vmctl.tail import run_tail, stream_file_events
from vmctl.transport import Connection, Transport, TransportError

TS = r"^\d{4}-\d{2}-\d{2}T"
AUDIT_LINE = '{"ig":{"routeId":"r1"},"timestamp":"2026-07-23T00:00:00.000Z","transactionId":"t"}'
ROUTE_LINES = [
    "2026-07-23T00:04:42,571Z | INFO | @00-proxy |",
    "[CONTINUED]GET http://127.0.0.1:9080/ HTTP/1.1",
    "2026-07-23T00:04:42,668Z | INFO | @00-proxy |",
    "[CONTINUED]response 200",
]


def _audit_profile() -> Profile:
    return Profile(
        name="p",
        hosts=[Host("h1", "u", password="x"), Host("h2", "u", password="x")],
        inputs=[Input(type="ig-audit", path=["*.json"], codec=Codec(name="json"))],
        base_dir="/logs",
    )


def _fake(lines: list[str]) -> FakeTransport:
    return FakeTransport(
        conn_factory=lambda h: FakeConnection(
            h, run_stdout=lambda _cmd: "access.audit.json\n", lines=lines
        )
    )


def test_stream_file_events_multiline() -> None:
    inp = Input(
        type="ig-route",
        path=["route-*.log"],
        codec=Codec(name="multiline", pattern=TS, negate=True, what="previous"),
    )
    profile = Profile(
        name="p",
        hosts=[],
        inputs=[inp],
        base_dir="/logs",
        filters=[
            Filter(condition='[type] == "ig-route"', grok={"path": r"route-%{DATA:route_id}\.log"})
        ],
    )
    conn = FakeConnection("h1", lines=ROUTE_LINES)

    async def collect() -> list[dict]:
        return [
            e
            async for e in stream_file_events(
                conn, host="h1", profile=profile, inp=inp, file_path="/logs/route-00-proxy.log"
            )
        ]

    events = asyncio.run(collect())
    assert len(events) == 2  # two timestamp-anchored events (last one via flush)
    assert events[0]["event"]["dataset"] == "ig-route"
    assert events[0]["labels"]["route_id"] == "00-proxy"
    assert "GET http://127.0.0.1:9080/" in events[0]["message"]


def test_run_tail_merges_two_hosts() -> None:
    events: list[dict] = []
    rc = asyncio.run(
        run_tail(
            _fake([AUDIT_LINE]),
            _audit_profile(),
            fallback_password=None,
            type_filter=None,
            write=events.append,
        )
    )
    assert rc == 0
    assert {e["host"]["name"] for e in events} == {"h1", "h2"}
    assert all(e["event"]["dataset"] == "ig-audit" for e in events)
    assert all(e["labels"]["route_id"] == "r1" for e in events)


def test_run_tail_type_filter() -> None:
    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="x")],
        inputs=[
            Input(type="ig-audit", path=["*.json"], codec=Codec(name="json")),
            Input(type="ig-system", path=["*.log"], codec=Codec(name="plain")),
        ],
        base_dir="/logs",
    )
    events: list[dict] = []
    rc = asyncio.run(
        run_tail(
            _fake([AUDIT_LINE]),
            profile,
            fallback_password=None,
            type_filter="ig-audit",
            write=events.append,
        )
    )
    assert rc == 0
    assert events and all(e["event"]["dataset"] == "ig-audit" for e in events)


def test_run_tail_unknown_type_errors() -> None:
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            _fake([AUDIT_LINE]),
            _audit_profile(),
            fallback_password=None,
            type_filter="nope",
            write=lambda _e: None,
            report_error=errors.append,
        )
    )
    assert rc == 1
    assert any("nope" in e for e in errors)


def test_run_tail_isolates_host_error() -> None:
    transport = FakeTransport(
        connect_error_hosts={"h1"},
        conn_factory=lambda h: FakeConnection(
            h, run_stdout=lambda _cmd: "access.audit.json\n", lines=[AUDIT_LINE]
        ),
    )
    events: list[dict] = []
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            transport,
            _audit_profile(),
            fallback_password=None,
            type_filter=None,
            write=events.append,
            report_error=errors.append,
            max_reconnects=0,  # bound the retry so h1 gives up instead of looping
            reconnect_base=0.0,
        )
    )
    assert rc == 1  # h1 gave up
    assert any("h1" in e for e in errors)
    assert {e["host"]["name"] for e in events} == {"h2"}  # h2 still streamed


class _SequenceTransport(Transport):
    """Hands out a preset connection per connect() call (for reconnect tests)."""

    def __init__(self, conns: list[FakeConnection]) -> None:
        self._it = iter(conns)
        self._last = conns[-1]

    async def connect(
        self, host: str, user: str, password: str, *, connect_timeout: float = 8.0
    ) -> Connection:
        return next(self._it, self._last)


def test_run_tail_reconnects_after_drop() -> None:
    dropped = FakeConnection(
        "h1",
        run_stdout=lambda _c: "a.json\n",
        lines=[AUDIT_LINE],
        stream_error=TransportError("h1", "connection lost"),
    )
    recovered = FakeConnection("h1", run_stdout=lambda _c: "a.json\n", lines=[AUDIT_LINE])
    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="x")],
        inputs=[Input(type="ig-audit", path=["*.json"], codec=Codec(name="json"))],
        base_dir="/logs",
    )
    events: list[dict] = []
    errors: list[str] = []
    asyncio.run(
        run_tail(
            _SequenceTransport([dropped, recovered]),
            profile,
            fallback_password=None,
            type_filter=None,
            write=events.append,
            report_error=errors.append,
            max_reconnects=1,
            reconnect_base=0.0,
        )
    )
    assert len(events) == 2  # one before the drop, one after reconnect
    assert any("reconnecting" in e for e in errors)


def test_run_tail_gives_up_after_max_reconnects() -> None:
    def drop(_h: str) -> FakeConnection:
        return FakeConnection(
            "h1",
            run_stdout=lambda _c: "a.json\n",
            lines=[],
            stream_error=TransportError("h1", "connection lost"),
        )

    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="x")],
        inputs=[Input(type="ig-audit", path=["*.json"], codec=Codec(name="json"))],
        base_dir="/logs",
    )
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            FakeTransport(conn_factory=drop),
            profile,
            fallback_password=None,
            type_filter=None,
            write=lambda _e: None,
            report_error=errors.append,
            max_reconnects=1,
            reconnect_base=0.0,
        )
    )
    assert rc == 1
    assert any("giving up" in e for e in errors)


def test_start_position_end_vs_beginning() -> None:
    profile = Profile(name="p", hosts=[], inputs=[], base_dir="/logs")

    def cmds_for(start_position: str) -> list[str]:
        conn = FakeConnection("h1", lines=[])
        inp = Input(type="t", path=["x"], codec=Codec(name="plain"), start_position=start_position)

        async def drain() -> None:
            async for _ in stream_file_events(
                conn, host="h1", profile=profile, inp=inp, file_path="/logs/x.log"
            ):
                pass

        asyncio.run(drain())
        return conn.stream_cmds

    assert any("tail -n 0 -F" in c for c in cmds_for("end"))
    assert any("tail -n +1 -F" in c for c in cmds_for("beginning"))
