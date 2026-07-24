"""Live search against the test lab. Requires the VMs up and VMCTL_SSH_PASSWORD.

Includes the milestone's soundness check: a pushed-down run and a full-scan run of the
same query must return exactly the same events. Run with: uv run pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from dslq import all_of, q, rng, term

from vmctl.config import load_config
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


FLUSH_WAIT = 4.0  # IG's audit write is async; measured ~1.06s, so this is ~4x margin


def _drive(count: int = 30) -> None:
    """Generate traffic, then wait for it to reach disk.

    IG's audit handler writes asynchronously, so a record lands on disk after the moment
    it timestamps. Waiting here — rather than shrinking the query window to dodge the
    race — means the tests below can bound exactly the traffic they generated.
    """
    subprocess.run(
        [sys.executable, str(DRIVE), "--count", str(count), "--delay", "0.03"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    time.sleep(FLUSH_WAIT)


def _search(clause: dict, **kw: Any) -> list[dict[str, Any]]:
    profile = load_config(EXAMPLE).profiles["test_ig"]
    events: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_search(
            AsyncSSHTransport(),
            profile,
            query=q(clause),
            fallback_password=_password(),
            write=events.append,
            **kw,
        )
    )
    assert rc == 0, "a host failed during the live search"
    return events


def _iso(at: datetime) -> str:
    """An absolute ISO-8601 bound — the DSL takes no date math (ADR 0007)."""
    return at.strftime("%Y-%m-%dT%H:%M:%S")


def _identity(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        event["host"]["name"],
        event["log"]["file"]["path"],
        event.get("message", ""),  # raw line — always present (ADR 0010)
    )


@pytest.mark.integration
def test_search_live_finds_audit_events_from_both_hosts() -> None:
    _drive()
    since = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    events = _search(
        all_of(term("event.dataset", "ig-audit"), rng("@timestamp", gte=since)),
        type_filter="ig-audit",
    )

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
    # `_drive` has already waited out the async audit write, so everything timestamped
    # at or before `now` is on disk — both runs therefore see the same bounded set.
    until_at = datetime.now(timezone.utc)
    query = all_of(
        term("event.dataset", "ig-audit"),
        term("response.statusCode", 200),
        rng(
            "@timestamp",
            gte=_iso(until_at - timedelta(minutes=30)),
            lte=_iso(until_at),
        ),
    )

    pushed = _search(query, type_filter="ig-audit")
    full = _search(query, type_filter="ig-audit", no_pushdown=True)

    assert pushed, "the query matched nothing — the comparison would be vacuous"
    assert {_identity(e) for e in pushed} == {_identity(e) for e in full}


@pytest.mark.integration
def test_route_id_selects_only_that_routes_file() -> None:
    """Tier-1 file selection: a route_id predicate opens only that route's log."""
    _drive()
    since = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    events = _search(
        all_of(
            term("event.dataset", "ig-route"),
            term("labels.route_id", "00-proxy"),
            rng("@timestamp", gte=since),
        ),
        type_filter="ig-route",
    )

    assert events, "no route-log events returned"
    paths = {e["log"]["file"]["path"] for e in events}
    assert all("route-00-proxy" in p for p in paths), paths
    assert all(e["labels"]["route_id"] == "00-proxy" for e in events)
