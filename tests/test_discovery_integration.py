"""Live discovery against the test lab. Requires the VMs up and VMCTL_SSH_PASSWORD.

Run with: uv run pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from vmctl.config import load_config
from vmctl.discovery import discover
from vmctl.transport import AsyncSSHTransport

EXAMPLE = Path(__file__).resolve().parents[1] / "testenv" / "infra" / "vmctl.example.yml"


@pytest.mark.integration
def test_discover_live_lab() -> None:
    password = os.environ.get("VMCTL_SSH_PASSWORD")
    if not password:
        pytest.skip("set VMCTL_SSH_PASSWORD to run the live discovery test")

    profile = load_config(EXAMPLE).profiles["test_ig"]
    result = asyncio.run(discover(AsyncSSHTransport(), profile, password))

    assert result.ok, [h.error for h in result.hosts if h.error]
    assert len(result.hosts) == 2
    for host in result.hosts:
        by_type = {mi.type: mi.files for mi in host.inputs}
        assert any("route-system.log" in f for f in by_type["ig-system"])
        assert by_type["ig-audit"], f"{host.host}: no audit file discovered"
