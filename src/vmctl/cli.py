"""Command-line entry point for vmctl.

Currently implements `discover` (list the files each rule matches on each host).
`tail` and `search` arrive in later milestones — see docs/milestones/.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vmctl import __version__
from vmctl.config import ConfigError, Profile, load_config
from vmctl.credentials import CredentialsError, resolve_password
from vmctl.discovery import DiscoveryError, discover
from vmctl.output import to_human, to_ndjson
from vmctl.tail import run_tail
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

    tail_p = sub.add_parser("tail", help="stream logs live across a profile's hosts")
    tail_p.add_argument("profile", help="profile name from the config")
    tail_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    tail_p.add_argument("--type", default=None, help="only stream this input type")
    tail_p.add_argument("--output", choices=["human", "ndjson"], default="human")
    tail_p.add_argument("--file", default=None, help="append output to this file instead of stdout")
    tail_p.set_defaults(func=cmd_tail)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


def _load_profile(args: argparse.Namespace) -> Profile | None:
    """Load the config and pick the requested profile, printing errors and returning
    None on failure."""
    from vmctl.config import default_config_path

    try:
        cfg = load_config(args.config or default_config_path())
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return None
    profile = cfg.profiles.get(args.profile)
    if profile is None:
        known = ", ".join(sorted(cfg.profiles)) or "(none)"
        print(f"unknown profile '{args.profile}'; known profiles: {known}", file=sys.stderr)
        return None
    return profile


def _fallback_password(profile: Profile) -> tuple[str | None, bool]:
    """Source a fallback password only if some host lacks an inline one. Returns
    (password, ok); ok is False when a credentials error was already reported."""
    if any(h.password is None for h in profile.hosts):
        try:
            return resolve_password(), True
        except CredentialsError as exc:
            print(f"credentials error: {exc}", file=sys.stderr)
            return None, False
    return None, True


def cmd_discover(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    if profile is None:
        return 1
    fallback, ok = _fallback_password(profile)
    if not ok:
        return 1

    try:
        result = asyncio.run(discover(AsyncSSHTransport(), profile, fallback))
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


def cmd_tail(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    if profile is None:
        return 1
    fallback, ok = _fallback_password(profile)
    if not ok:
        return 1

    render = to_ndjson if args.output == "ndjson" else to_human
    out = open(args.file, "a", encoding="utf-8") if args.file else sys.stdout

    def write(event: dict[str, object]) -> None:
        print(render(event), file=out, flush=True)

    try:
        return asyncio.run(
            run_tail(
                AsyncSSHTransport(),
                profile,
                fallback_password=fallback,
                type_filter=args.type,
                write=write,
                report_error=lambda msg: print(msg, file=sys.stderr),
            )
        )
    except KeyboardInterrupt:
        return 0
    finally:
        if args.file:
            out.close()
