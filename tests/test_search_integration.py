"""Live search against the test lab. Requires the VMs up and VMCTL_SSH_PASSWORD.

Includes the milestone's soundness check: a pushed-down run and a full-scan run of the
same query must return exactly the same events. Run with: uv run pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from vmctl.config import load_config
from vmctl.kql import parse
from vmctl.search import run_search
from vmctl.transport import AsyncSSHTransport

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "testenv" / "infra" / "vmctl.example.yml"
DRIVE = ROOT / "testenv" / "engine" / "drive.py"


def _password() -> str:
    password = os.environ.get("VMCTL_SSH_PASSWORD")
    if not password:
        pytest.skip("set VMCTL_SSH_PASSWORD to run the live search tests")
    return password


def _drive(count: int = 30) -> None:
    subprocess.run(
        [sys.executable, str(DRIVE), "--count", str(count), "--delay", "0.03"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _search(query: str, **kw: Any) -> list[dict[str, Any]]:
    profile = load_config(EXAMPLE).profiles["test_ig"]
    events: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_search(
            AsyncSSHTransport(),
            profile,
            query=parse(query),
            fallback_password=_password(),
            write=events.append,
            **kw,
        )
    )
    assert rc == 0, "a host failed during the live search"
    return events


def _identity(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        event["host"]["name"],
        event["log"]["file"]["path"],
        event.get("event", {}).get("original", ""),
    )


@pytest.mark.integration
def test_search_live_finds_audit_events_from_both_hosts() -> None:
    _drive()
    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    events = _search("event.dataset:ig-audit", type_filter="ig-audit", since=since)

    assert events, "no events returned from the live search"
    hosts = {e["host"]["name"] for e in events}
    assert "192.168.77.11" in hosts and "192.168.77.12" in hosts, hosts
    assert all(e["event"]["dataset"] == "ig-audit" for e in events)
    # Results arrive in chronological order across hosts.
    stamps = [e["@timestamp"] for e in events]
    assert stamps == sorted(stamps)


@pytest.mark.integration
def test_pushdown_is_sound() -> None:
    """Pushed-down results must equal a full scan filtered on the client."""
    _drive()
    # A closed window makes both runs see the same bounded set even if traffic continues.
    # It has to end in the *past*: IG's audit write is asynchronous (measured ~1s), so a
    # record can land on disk after the moment it timestamps. Ending the window at `now`
    # would let a flush arrive between the two runs and add events the first never saw.
    # A minute of margin makes the comparison independent of that latency entirely.
    until = datetime.now(timezone.utc) - timedelta(minutes=1)
    since = until - timedelta(minutes=30)
    query = "event.dataset:ig-audit and response.statusCode:200"

    pushed = _search(query, type_filter="ig-audit", since=since, until=until)
    full = _search(query, type_filter="ig-audit", since=since, until=until, no_pushdown=True)

    assert pushed, "the query matched nothing — the comparison would be vacuous"
    assert {_identity(e) for e in pushed} == {_identity(e) for e in full}


@pytest.mark.integration
def test_route_id_selects_only_that_routes_file() -> None:
    """Tier-1 file selection: a route_id predicate opens only that route's log."""
    _drive()
    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    events = _search(
        "event.dataset:ig-route and labels.route_id:00-proxy",
        type_filter="ig-route",
        since=since,
    )

    assert events, "no route-log events returned"
    paths = {e["log"]["file"]["path"] for e in events}
    assert all("route-00-proxy" in p for p in paths), paths
    assert all(e["labels"]["route_id"] == "00-proxy" for e in events)
