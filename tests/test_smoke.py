"""Smoke tests for the empty framework — prove the package imports, the version
is exposed, and the CLI entry point runs. No product behaviour yet."""

from __future__ import annotations

import pytest

import vmctl
from vmctl.cli import main


def test_version_is_nonempty_string() -> None:
    assert isinstance(vmctl.__version__, str)
    assert vmctl.__version__


def test_cli_version_flag_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_cli_no_args_returns_zero() -> None:
    assert main([]) == 0
