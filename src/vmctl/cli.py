"""Command-line entry point for vmctl.

This is the empty scaffold: it wires up ``vmctl --version`` / ``vmctl --help``
and nothing else. Product subcommands (stream, search) arrive in later
milestones — see docs/milestones/.
"""

from __future__ import annotations

import argparse

from vmctl import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    Subcommands are added in later milestones; for now the parser only
    exposes ``--version`` and the built-in ``--help``.
    """
    parser = argparse.ArgumentParser(
        prog="vmctl",
        description=(
            "Stream and search ForgeRock logs across identical SSH-reachable deployments."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"vmctl {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code.

    With no arguments, prints help and exits 0 — there is nothing to do yet.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
