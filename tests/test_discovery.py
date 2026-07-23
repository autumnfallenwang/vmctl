"""Fast tests for remote discovery (fake transport, no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes import FakeConnection, FakeTransport

from vmctl.config import Host, Input, Profile, load_config
from vmctl.discovery import (
    DiscoveryError,
    apply_excludes,
    build_glob_command,
    discover,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "testenv" / "infra" / "vmctl.example.yml"


def test_build_glob_command() -> None:
    cmd = build_glob_command("/opt/ig-instance/logs", ["route-*.log*", "audit/*.audit.json*"])
    assert "cd '/opt/ig-instance/logs'" in cmd
    assert "nullglob" in cmd
    assert "route-*.log* audit/*.audit.json*" in cmd


def test_build_glob_command_rejects_unsafe() -> None:
    with pytest.raises(DiscoveryError):
        build_glob_command("/logs", ["foo; rm -rf /"])
    with pytest.raises(DiscoveryError):
        build_glob_command("/lo'gs", ["*.log"])


def test_apply_excludes() -> None:
    files = ["route-00-proxy.log", "route-login.log", "route-system.log"]
    assert apply_excludes(files, ["route-system.log*"]) == ["route-00-proxy.log", "route-login.log"]


def _lab_stdout(cmd: str) -> str:
    # Simulate the remote glob output based on which input's globs are in the command.
    # Note both a base and a *rotated* system log, to prove the exclude catches both.
    if "route-system*" in cmd:  # ig-system
        return "route-system.log\nroute-system-2026-07-22.0.log\n"
    if "route-*.log*" in cmd:  # ig-route (glob matches route + rotated system logs)
        return (
            "route-00-proxy.log\nroute-login.log\nroute-system.log\nroute-system-2026-07-22.0.log\n"
        )
    if "audit/" in cmd:
        return "audit/access.audit.json\n"
    return ""


def test_discover_per_host_per_input() -> None:
    profile = load_config(EXAMPLE).profiles["test_ig"]
    transport = FakeTransport(conn_factory=lambda h: FakeConnection(h, run_stdout=_lab_stdout))
    result = asyncio.run(discover(transport, profile, "pw"))

    assert result.ok
    assert [h.host for h in result.hosts] == ["192.168.77.11", "192.168.77.12"]
    for host in result.hosts:
        by_type = {mi.type: mi.files for mi in host.inputs}
        assert by_type["ig-system"] == ["route-system.log", "route-system-2026-07-22.0.log"]
        # ig-route excludes both base and rotated system logs even though the glob matched them
        assert by_type["ig-route"] == ["route-00-proxy.log", "route-login.log"]
        assert by_type["ig-audit"] == ["audit/access.audit.json"]


def test_inline_password_takes_priority_over_fallback() -> None:
    profile = Profile(
        name="p",
        hosts=[Host("h1", "u", password="inline"), Host("h2", "u")],  # h2 has no inline pw
        inputs=[Input(type="t", path=["x"])],
    )
    transport = FakeTransport(conn_factory=lambda h: FakeConnection(h, run_stdout=lambda _c: "f\n"))
    result = asyncio.run(discover(transport, profile, "fallback"))

    assert result.ok
    used = {host: pw for host, _user, pw in transport.calls}
    assert used["h1"] == "inline"  # inline password wins
    assert used["h2"] == "fallback"  # falls back when no inline password


def test_no_password_available_errors_that_host() -> None:
    profile = Profile(name="p", hosts=[Host("h1", "u")], inputs=[Input(type="t", path=["x"])])
    result = asyncio.run(discover(FakeTransport(), profile, None))  # no inline, no fallback
    assert result.ok is False
    assert "no password" in str(result.hosts[0].error)


def test_discover_isolates_host_error() -> None:
    profile = load_config(EXAMPLE).profiles["test_ig"]
    transport = FakeTransport(
        connect_error_hosts={"192.168.77.12"},
        conn_factory=lambda h: FakeConnection(h, run_stdout=_lab_stdout),
    )
    result = asyncio.run(discover(transport, profile, "pw"))

    assert result.ok is False
    by_host = {h.host: h for h in result.hosts}
    assert by_host["192.168.77.12"].error is not None
    assert by_host["192.168.77.11"].error is None
    assert by_host["192.168.77.11"].inputs  # the good host still discovered
