"""Live tail against the test lab. Requires the VMs up and VMCTL_SSH_PASSWORD.

Runs `run_tail` on the audit input, drives traffic with the test engine, and
asserts events streamed from both hosts. Run with: uv run pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from vmctl.config import load_config
from vmctl.tail import run_tail
from vmctl.transport import AsyncSSHTransport

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "testenv" / "infra" / "vmctl.example.yml"
DRIVE = ROOT / "testenv" / "engine" / "drive.py"


@pytest.mark.integration
def test_tail_live_receives_events_from_both_hosts() -> None:
    password = os.environ.get("VMCTL_SSH_PASSWORD")
    if not password:
        pytest.skip("set VMCTL_SSH_PASSWORD to run the live tail test")

    profile = load_config(EXAMPLE).profiles["test_ig"]
    events: list[dict] = []

    async def scenario() -> None:
        task = asyncio.create_task(
            run_tail(
                AsyncSSHTransport(),
                profile,
                fallback_password=password,
                type_filter="ig-audit",
                write=events.append,
            )
        )
        await asyncio.sleep(2)  # let the tails attach
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(DRIVE),
            "--count",
            "30",
            "--delay",
            "0.03",
            cwd=str(ROOT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        await asyncio.sleep(2)  # let events flow back
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert events, "no events streamed from the live tail"
    hosts = {e["host"]["name"] for e in events}
    assert "192.168.77.11" in hosts and "192.168.77.12" in hosts, hosts
    assert all(e["event"]["dataset"] == "ig-audit" for e in events)
