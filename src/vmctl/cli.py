"""Command-line entry point for vmctl.

Currently implements `discover` (list the files each rule matches on each host).
`tail` and `search` arrive in later milestones — see docs/milestones/.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vmctl import __version__
from vmctl.config import ConfigError, load_config
from vmctl.credentials import CredentialsError, resolve_password
from vmctl.discovery import DiscoveryError, discover
from vmctl.transport import AsyncSSHTransport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vmctl",
        description=(
            "Stream and search ForgeRock logs across identical SSH-reachable deployments."
        ),
    )
    parser.add_argument("--version", action="version", version=f"vmctl {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    discover_p = sub.add_parser(
        "discover", help="list the log files each rule matches on each host"
    )
    discover_p.add_argument("profile", help="profile name from the config")
    discover_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    discover_p.set_defaults(func=cmd_discover)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


def cmd_discover(args: argparse.Namespace) -> int:
    from vmctl.config import default_config_path

    try:
        cfg = load_config(args.config or default_config_path())
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    profile = cfg.profiles.get(args.profile)
    if profile is None:
        known = ", ".join(sorted(cfg.profiles)) or "(none)"
        print(f"unknown profile '{args.profile}'; known profiles: {known}", file=sys.stderr)
        return 1

    # Only source a fallback password if some host lacks an inline one.
    fallback_password = None
    if any(h.password is None for h in profile.hosts):
        try:
            fallback_password = resolve_password()
        except CredentialsError as exc:
            print(f"credentials error: {exc}", file=sys.stderr)
            return 1

    try:
        result = asyncio.run(discover(AsyncSSHTransport(), profile, fallback_password))
    except DiscoveryError as exc:
        print(f"discovery error: {exc}", file=sys.stderr)
        return 1

    for host in result.hosts:
        if host.error is not None:
            print(f"{host.host}: ERROR {host.error}", file=sys.stderr)
            continue
        for matched in host.inputs:
            files = ", ".join(matched.files) if matched.files else "(no files matched)"
            print(f"{host.host}  {matched.type}: {files}")

    return 0 if result.ok else 1
