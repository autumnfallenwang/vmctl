"""Fast tests for password sourcing."""

from __future__ import annotations

import pytest

from vmctl.credentials import CredentialsError, resolve_password


def test_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMCTL_SSH_PASSWORD", "s3cret")
    assert resolve_password() == "s3cret"


def test_no_password_non_interactive_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VMCTL_SSH_PASSWORD", raising=False)
    with pytest.raises(CredentialsError, match="VMCTL_SSH_PASSWORD"):
        resolve_password(allow_prompt=False)
