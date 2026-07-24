"""Fast tests for the tail streaming pipeline (fake transport, no network)."""

from __future__ import annotations

import asyncio

from fakes import FakeConnection, FakeTransport

from vmctl.config import Codec, Filter, Host, Input, Profile
from vmctl.tail import _remote_path, run_tail, stream_input_events
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


def test_tail_remote_path_leaves_absolute_glob_unjoined() -> None:
    # M12 bug #1 (tail's copy): absolute discovered path must not get base_dir prepended.
    assert _remote_path("/logs", "/opt/sso/debug/IdRepo") == "/opt/sso/debug/IdRepo"
    assert _remote_path("/logs", "sub/route.log") == "/logs/sub/route.log"


def test_run_tail_multiplexes_all_files_of_an_input_over_one_channel() -> None:
    # ADR 0012 (the real fix for M12 #2): 12 files used to need 12 channels and blow past
    # MaxSessions; now they ride ONE `tail -F` per input, well under the cap of 8.
    paths = [f"r{i}.log" for i in range(12)]
    conn = FakeConnection("h1", run_stdout=lambda _c: "\n".join(paths) + "\n", lines=[])
    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="x")],
        inputs=[Input(type="t", path=["*.log"], codec=Codec(name="plain"))],
        base_dir="/logs",
    )
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            FakeTransport(conn_factory=lambda _h: conn),
            profile,
            fallback_password=None,
            type_filter=None,
            write=lambda _e: None,
            report_error=errors.append,
        )
    )
    assert rc == 0 and errors == []
    assert len(conn.stream_cmds) == 1  # one channel, not twelve
    assert all(f"'/logs/{p}'" in conn.stream_cmds[0] for p in paths)


def test_run_tail_refuses_when_channels_exceed_cap() -> None:
    # The cap now bounds *channels* (= inputs), not files: 3 inputs vs cap 2 → one clear
    # refusal, and no channel opened.
    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="x")],
        inputs=[
            Input(type="a", path=["a*.log"], codec=Codec(name="plain")),
            Input(type="b", path=["b*.log"], codec=Codec(name="plain")),
            Input(type="c", path=["c*.log"], codec=Codec(name="plain")),
        ],
        base_dir="/logs",
        max_concurrent_files=2,
    )
    conn = FakeConnection("h1", run_stdout=lambda _c: "x.log\n", lines=[])
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            FakeTransport(conn_factory=lambda _h: conn),
            profile,
            fallback_password=None,
            type_filter=None,
            write=lambda _e: None,
            report_error=errors.append,
            max_reconnects=0,
            reconnect_base=0.0,
        )
    )
    assert rc == 1
    assert any("max_concurrent_files=2" in e and "3 tail channels" in e for e in errors)
    assert conn.stream_cmds == []  # refused before opening any tail channel


def _multiplexed(lines: list[str], paths: list[str]) -> list[dict]:
    """Drive stream_input_events over a canned multi-file tail stream."""
    inp = Input(type="t", path=["*.log"], codec=Codec(name="plain"))
    profile = Profile(name="p", hosts=[], inputs=[inp], base_dir="/logs")
    conn = FakeConnection("h1", lines=lines)

    async def collect() -> list[dict]:
        return [
            e
            async for e in stream_input_events(
                conn, host="h1", profile=profile, inp=inp, file_paths=paths
            )
        ]

    return asyncio.run(collect())


def test_tail_routes_lines_to_the_file_named_by_the_header() -> None:
    # Exactly the byte stream Rocky 9 coreutils 8.32 produces: startup headers, a blank
    # separator before every header but the first, switch-only headers.
    events = _multiplexed(
        [
            "==> /logs/a.log <==",
            "a1",
            "",
            "==> /logs/b.log <==",
            "b1",
            "",
            "==> /logs/a.log <==",
            "a2",
            "a3",
        ],
        ["/logs/a.log", "/logs/b.log"],
    )
    assert [(e["log"]["file"]["path"], e["message"]) for e in events] == [
        ("/logs/a.log", "a1"),
        ("/logs/b.log", "b1"),
        ("/logs/a.log", "a2"),
        ("/logs/a.log", "a3"),
    ]


def test_tail_keeps_a_real_blank_line_but_drops_the_separator() -> None:
    # Two blanks in a row: the first is content, the second is the header separator.
    events = _multiplexed(
        ["==> /logs/a.log <==", "a1", "", "", "==> /logs/b.log <==", "b1"],
        ["/logs/a.log", "/logs/b.log"],
    )
    assert [(e["log"]["file"]["path"], e["message"]) for e in events] == [
        ("/logs/a.log", "a1"),
        ("/logs/a.log", ""),
        ("/logs/b.log", "b1"),
    ]


def test_tail_ignores_a_spoofed_header_for_an_unwatched_path() -> None:
    # A log line that merely looks like a header must not redirect attribution.
    events = _multiplexed(
        ["==> /logs/a.log <==", "a1", "==> /etc/shadow <==", "a2"],
        ["/logs/a.log", "/logs/b.log"],
    )
    assert [(e["log"]["file"]["path"], e["message"]) for e in events] == [
        ("/logs/a.log", "a1"),
        ("/logs/a.log", "==> /etc/shadow <=="),  # kept as content
        ("/logs/a.log", "a2"),
    ]


def test_run_tail_host_filter_scopes() -> None:
    # M12 #4: --host narrows tail to the named host.
    events: list[dict] = []
    rc = asyncio.run(
        run_tail(
            _fake([AUDIT_LINE]),
            _audit_profile(),
            fallback_password=None,
            type_filter=None,
            host_filter={"h2"},
            write=events.append,
        )
    )
    assert rc == 0
    assert {e["host"]["name"] for e in events} == {"h2"}


def test_run_tail_unknown_host_errors() -> None:
    errors: list[str] = []
    rc = asyncio.run(
        run_tail(
            _fake([AUDIT_LINE]),
            _audit_profile(),
            fallback_password=None,
            type_filter=None,
            host_filter={"nope"},
            write=lambda _e: None,
            report_error=errors.append,
        )
    )
    assert rc == 1
    assert any("nope" in e and "unknown host" in e for e in errors)


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
            async for e in stream_input_events(
                conn,
                host="h1",
                profile=profile,
                inp=inp,
                file_paths=["/logs/route-00-proxy.log"],
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
    # route_id is no longer auto-mirrored (ADR 0010); this inline profile has no filter.
    assert all("route_id" not in e.get("labels", {}) for e in events)


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
            async for _ in stream_input_events(
                conn, host="h1", profile=profile, inp=inp, file_paths=["/logs/x.log"]
            ):
                pass

        asyncio.run(drain())
        return conn.stream_cmds

    assert any("tail -n 0 -F" in c for c in cmds_for("end"))
    assert any("tail -n +1 -F" in c for c in cmds_for("beginning"))
