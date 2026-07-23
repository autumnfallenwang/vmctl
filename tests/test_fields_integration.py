"""Live field discovery against the test lab. Requires the VMs up and VMCTL_SSH_PASSWORD.

Run with: uv run pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from dslq import exists, q

from vmctl.config import load_config
from vmctl.fields import run_fields
from vmctl.query import matches
from vmctl.search import run_search
from vmctl.transport import AsyncSSHTransport

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "testenv" / "infra" / "vmctl.example.yml"
DRIVE = ROOT / "testenv" / "engine" / "drive.py"


def _password() -> str:
    password = os.environ.get("VMCTL_SSH_PASSWORD")
    if not password:
        pytest.skip("set VMCTL_SSH_PASSWORD to run the live fields test")
    return password


def _fields() -> dict[str, Any]:
    profile = load_config(EXAMPLE).profiles["test_ig"]
    captured: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_fields(
            AsyncSSHTransport(),
            profile,
            fallback_password=_password(),
            write=captured.append,
        )
    )
    assert rc == 0, "a host failed during field discovery"
    return captured[0]


@pytest.mark.integration
def test_fields_live_reports_all_datasets() -> None:
    # Drive a little traffic so the audit log has fresh records to sample.
    subprocess.run(
        [sys.executable, str(DRIVE), "--count", "20", "--delay", "0.03"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    time.sleep(4)

    caps = _fields()

    assert set(caps["indices"]) == {"ig-audit", "ig-route", "ig-system"}
    assert "192.168.77.11" in caps["vmctl"]["hosts"]
    assert "192.168.77.12" in caps["vmctl"]["hosts"]

    # statusCode is an audit-only string field.
    status = caps["fields"]["response.statusCode"]
    assert "keyword" in status
    assert status["keyword"]["indices"] == ["ig-audit"]

    # A header array is reported at its queryable path, not `...host.0`.
    assert "http.request.headers.host" in caps["fields"]
    assert not any(part.isdigit() for part in "http.request.headers.host".split("."))
    assert not any(
        f.startswith("http.request.headers.host.") and f.split(".")[-1].isdigit()
        for f in caps["fields"]
    )

    # The ECS envelope is present and uniform (no per-field indices).
    assert "indices" not in caps["fields"]["@timestamp"]["date"]


@pytest.mark.integration
def test_discovered_field_round_trips_through_search() -> None:
    caps = _fields()
    profile = load_config(EXAMPLE).profiles["test_ig"]

    # Pick a discovered audit field and prove a search on it returns events.
    assert "response.statusCode" in caps["fields"]
    events: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_search(
            AsyncSSHTransport(),
            profile,
            query=q(exists("response.statusCode")),
            fallback_password=_password(),
            type_filter="ig-audit",
            write=events.append,
        )
    )
    assert rc == 0
    assert events, "a discovered field returned no search hits"
    assert all(matches(q(exists("response.statusCode")), e) for e in events)
