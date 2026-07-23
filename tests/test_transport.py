"""Fast tests for the transport fan-out (fake transport, no network)."""

from __future__ import annotations

import asyncio

from fakes import FakeConnection, FakeTransport

from vmctl.config import Host
from vmctl.transport import TransportError, run_on_hosts

HOSTS = [Host("h1", "u"), Host("h2", "u")]


def test_run_on_hosts_success() -> None:
    transport = FakeTransport(conn_factory=lambda h: FakeConnection(h, run_stdout=lambda _c: "ok"))
    outcomes = asyncio.run(run_on_hosts(transport, HOSTS, "pw", "hostname"))
    assert {o.host for o in outcomes} == {"h1", "h2"}
    assert all(o.error is None and o.result is not None for o in outcomes)
    assert all(o.result.stdout == "ok" for o in outcomes if o.result)


def test_run_on_hosts_isolates_connect_failure() -> None:
    transport = FakeTransport(connect_error_hosts={"h1"})
    outcomes = {o.host: o for o in asyncio.run(run_on_hosts(transport, HOSTS, "pw", "hostname"))}
    assert outcomes["h1"].error is not None and outcomes["h1"].result is None
    assert outcomes["h2"].error is None and outcomes["h2"].result is not None


def test_run_on_hosts_run_failure_still_closes() -> None:
    made: list[FakeConnection] = []

    def factory(h: str) -> FakeConnection:
        conn = FakeConnection(h, run_error=TransportError(h, "boom"))
        made.append(conn)
        return conn

    transport = FakeTransport(conn_factory=factory)
    outcomes = asyncio.run(run_on_hosts(transport, [Host("h1", "u")], "pw", "hostname"))
    assert outcomes[0].error is not None
    assert made[0].closed is True  # close() ran despite the run() failure


def test_stream_yields_lines() -> None:
    conn = FakeConnection("h1", lines=["a", "b", "c"])

    async def collect() -> list[str]:
        return [line async for line in conn.stream("tail -F x")]

    assert asyncio.run(collect()) == ["a", "b", "c"]
