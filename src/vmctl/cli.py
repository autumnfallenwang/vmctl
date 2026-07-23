"""Command-line entry point for vmctl.

Four subcommands: `discover` (list the files each input matches on each host),
`tail` (follow them live), `search` (bounded read + Query DSL filter), and `fields`
(what is queryable, in Elasticsearch `_field_caps` shape).

vmctl is a machine interface (docs/adr/0007): every command emits **NDJSON only**, one
JSON object per line, and `search` takes its filter as **Elasticsearch Query DSL** — the
same JSON you would put in the body of `POST /<index>/_search`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from vmctl import __version__
from vmctl.config import ConfigError, Profile, load_config
from vmctl.credentials import CredentialsError, resolve_password
from vmctl.discovery import DiscoveryError, discover
from vmctl.dsl import DSLError, parse_dsl
from vmctl.fields import run_fields
from vmctl.output import to_ndjson
from vmctl.search import run_search
from vmctl.tail import run_tail
from vmctl.transport import AsyncSSHTransport


_EPILOG = (
    "Output: every command emits NDJSON (one JSON object per line) on stdout; there is no "
    "human-readable mode. Pipe through `jq` to read it by eye.\n"
    "Query: `search` takes an Elasticsearch Query DSL filter; run `fields` first to discover "
    "what you can filter on.\n"
    "Password: each host may carry an inline `password:` in the config; otherwise vmctl reads "
    "$VMCTL_SSH_PASSWORD, then falls back to an interactive prompt."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vmctl",
        description=(
            "Stream and search ForgeRock logs across identical SSH-reachable deployments."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"vmctl {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    discover_p = sub.add_parser(
        "discover", help="list the log files each input matches on each host"
    )
    discover_p.add_argument("profile", help="profile name from the config")
    discover_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    discover_p.set_defaults(func=cmd_discover)

    tail_p = sub.add_parser("tail", help="stream logs live across a profile's hosts")
    tail_p.add_argument("profile", help="profile name from the config")
    tail_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    tail_p.add_argument("--type", default=None, help="only stream this input type")
    tail_p.add_argument("--file", default=None, help="append output to this file instead of stdout")
    tail_p.set_defaults(func=cmd_tail)

    search_p = sub.add_parser(
        "search", help="search logs across a profile's hosts with an Elasticsearch Query DSL filter"
    )
    search_p.add_argument("profile", help="profile name from the config")
    search_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    search_p.add_argument(
        "--filter",
        default=None,
        help='Query DSL as JSON, e.g. \'{"term":{"event.dataset":"ig-audit"}}\'. '
        "Reads stdin when neither --filter nor --filter-file is given.",
    )
    search_p.add_argument("--filter-file", default=None, help="read the Query DSL from a file")
    search_p.add_argument("--type", default=None, help="only search this input type")
    search_p.add_argument(
        "--file", default=None, help="append output to this file instead of stdout"
    )
    search_p.add_argument(
        "--no-pushdown",
        action="store_true",
        help="read whole files and filter locally (baseline for verifying pushdown)",
    )
    search_p.set_defaults(func=cmd_search)

    fields_p = sub.add_parser(
        "fields", help="report what is queryable, in Elasticsearch _field_caps shape"
    )
    fields_p.add_argument("profile", help="profile name from the config")
    fields_p.add_argument("--config", default=None, help="path to the profile config (YAML)")
    fields_p.add_argument("--type", default=None, help="only sample this input type")
    fields_p.add_argument(
        "--sample", type=int, default=500, help="records to sample per input (default 500)"
    )
    fields_p.set_defaults(func=cmd_fields)

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


def _read_filter(args: argparse.Namespace) -> str:
    """The Query DSL text, from --filter, --filter-file, or stdin."""
    if args.filter and args.filter_file:
        raise DSLError("give either --filter or --filter-file, not both")
    if args.filter:
        return args.filter
    if args.filter_file:
        try:
            with open(args.filter_file, encoding="utf-8") as handle:
                return handle.read()
        except OSError as exc:
            raise DSLError(f"cannot read --filter-file: {exc}") from exc
    if sys.stdin.isatty():
        raise DSLError("no filter given — pass --filter, --filter-file, or pipe JSON on stdin")
    return sys.stdin.read()


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

    # NDJSON, like every other command: one object per host/input pair.
    for host in result.hosts:
        if host.error is not None:
            print(f"ERROR: {host.error}", file=sys.stderr)  # host.error already names the host
            continue
        for matched in host.inputs:
            print(
                json.dumps(
                    {"host": {"name": host.host}, "type": matched.type, "files": matched.files},
                    separators=(",", ":"),
                ),
                flush=True,
            )

    return 0 if result.ok else 1


def cmd_tail(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    if profile is None:
        return 1
    fallback, ok = _fallback_password(profile)
    if not ok:
        return 1

    out = open(args.file, "a", encoding="utf-8") if args.file else sys.stdout

    def write(event: dict[str, object]) -> None:
        print(to_ndjson(event), file=out, flush=True)

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


def cmd_search(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    if profile is None:
        return 1

    # Fail on a bad filter before prompting for a password.
    try:
        query = parse_dsl(_read_filter(args))
    except DSLError as exc:
        print(f"query error: {exc}", file=sys.stderr)
        return 1

    fallback, ok = _fallback_password(profile)
    if not ok:
        return 1

    out = open(args.file, "a", encoding="utf-8") if args.file else sys.stdout

    def write(event: dict[str, object]) -> None:
        print(to_ndjson(event), file=out, flush=True)

    try:
        return asyncio.run(
            run_search(
                AsyncSSHTransport(),
                profile,
                query=query,
                fallback_password=fallback,
                type_filter=args.type,
                write=write,
                report_error=lambda msg: print(msg, file=sys.stderr),
                no_pushdown=args.no_pushdown,
            )
        )
    except KeyboardInterrupt:
        return 0
    finally:
        if args.file:
            out.close()


def cmd_fields(args: argparse.Namespace) -> int:
    profile = _load_profile(args)
    if profile is None:
        return 1
    fallback, ok = _fallback_password(profile)
    if not ok:
        return 1

    def write(result: dict[str, object]) -> None:
        print(to_ndjson(result), flush=True)

    try:
        return asyncio.run(
            run_fields(
                AsyncSSHTransport(),
                profile,
                fallback_password=fallback,
                type_filter=args.type,
                sample=args.sample,
                write=write,
                report_error=lambda msg: print(msg, file=sys.stderr),
            )
        )
    except KeyboardInterrupt:
        return 0
