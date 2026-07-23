"""Fast tests for `run_search` — the three tiers wired together (fake transport)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from dslq import all_of, q, rng, term
from fakes import FakeConnection, FakeTransport

from vmctl.config import Codec, Host, Input, Profile
from vmctl.search import run_search

EARLY = "2026-07-23T00:00:01.000Z"
LATE = "2026-07-23T00:00:09.000Z"


def _audit(timestamp: str, status: str = "200", route: str = "00-proxy") -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "response": {"statusCode": status},
            "ig": {"routeId": route},
        },
        separators=(",", ":"),
    )


def _profile(*hosts: str) -> Profile:
    return Profile(
        name="p",
        hosts=[Host(h, "u", password="x") for h in (hosts or ("h1",))],
        inputs=[Input(type="ig-audit", path=["audit/*.json"], codec=Codec(name="json"))],
        base_dir="/logs",
    )


def _transport(content: dict[str, str] | str, **kw: Any) -> FakeTransport:
    """A transport whose glob returns one audit file and whose reads return `content`
    (per host when a dict) regardless of any pushdown — so the remote side always hands
    back a superset and tier 3 has to do the real work."""

    def factory(host: str) -> FakeConnection:
        body = content[host] if isinstance(content, dict) else content

        def stdout(cmd: str) -> str:
            return "audit/access.audit.json\n" if cmd.startswith("cd ") else body

        return FakeConnection(host, run_stdout=stdout)

    return FakeTransport(conn_factory=factory, **kw)


def _search(
    transport: FakeTransport, profile: Profile, clause: dict, **kw: Any
) -> tuple[int, list]:
    events: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_search(
            transport,
            profile,
            query=q(clause),
            fallback_password=None,
            write=events.append,
            **kw,
        )
    )
    return rc, events


def test_search_returns_only_matches() -> None:
    body = f"{_audit(EARLY, '500')}\n{_audit(LATE, '200')}\n"
    rc, events = _search(_transport(body), _profile(), term("response.statusCode", 500))
    assert rc == 0
    assert len(events) == 1
    assert events[0]["response"]["statusCode"] == "500"


def test_search_tier1_skips_non_matching_host() -> None:
    transport = _transport(f"{_audit(EARLY)}\n")
    rc, events = _search(transport, _profile("h1", "h2"), term("host.name", "h1"))
    assert rc == 0
    # h2 was never even connected to — the predicate was resolved by the planner.
    assert [call[0] for call in transport.calls] == ["h1"]
    assert {e["host"]["name"] for e in events} == {"h1"}


def test_search_no_pushdown_uses_cat() -> None:
    windowed = all_of(
        term("event.dataset", "ig-audit"), rng("@timestamp", gte="2026-07-23T00:00:05")
    )
    body = f"{_audit(LATE)}\n"

    pushed = _transport(body)
    _search(pushed, _profile(), windowed)
    assert any(c.startswith("awk ") for c in pushed.connections[0].run_cmds)

    full = _transport(body)
    _search(full, _profile(), windowed, no_pushdown=True)
    read_cmds = [c for c in full.connections[0].run_cmds if not c.startswith("cd ")]
    assert read_cmds == ["cat '/logs/audit/access.audit.json'"]


def test_search_time_window_is_exact_client_side() -> None:
    # The fake returns both lines whatever the window — tier 3 must still drop the early
    # one, which is exactly the superset contract tier 2 works under.
    body = f"{_audit(EARLY)}\n{_audit(LATE)}\n"
    rc, events = _search(
        _transport(body),
        _profile(),
        all_of(term("event.dataset", "ig-audit"), rng("@timestamp", gte="2026-07-23T00:00:05")),
    )
    assert rc == 0
    assert [e["timestamp"] for e in events] == [LATE]


def test_search_results_sorted_by_timestamp() -> None:
    transport = _transport({"h1": f"{_audit(LATE)}\n", "h2": f"{_audit(EARLY)}\n"})
    rc, events = _search(transport, _profile("h1", "h2"), term("event.dataset", "ig-audit"))
    assert rc == 0
    assert [e["timestamp"] for e in events] == [EARLY, LATE]


def test_search_isolates_host_error() -> None:
    transport = _transport(f"{_audit(EARLY)}\n", connect_error_hosts={"h1"})
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_search(
            transport,
            _profile("h1", "h2"),
            query=q(term("event.dataset", "ig-audit")),
            fallback_password=None,
            write=events.append,
            report_error=errors.append,
        )
    )
    assert rc == 1
    assert any("h1" in e for e in errors)
    assert {e["host"]["name"] for e in events} == {"h2"}


def test_search_unknown_type_errors() -> None:
    errors: list[str] = []
    rc = asyncio.run(
        run_search(
            _transport(""),
            _profile(),
            query=q(term("event.dataset", "ig-audit")),
            fallback_password=None,
            type_filter="nope",
            write=lambda _e: None,
            report_error=errors.append,
        )
    )
    assert rc == 1
    assert any("nope" in e for e in errors)


def test_search_reports_scan_summary() -> None:
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    asyncio.run(
        run_search(
            _transport(f"{_audit(EARLY)}\n"),
            _profile(),
            query=q(term("event.dataset", "ig-audit")),
            fallback_password=None,
            write=events.append,
            report_error=errors.append,
        )
    )
    assert any("scanned 1 file(s); 1 match(es)" in e for e in errors)
