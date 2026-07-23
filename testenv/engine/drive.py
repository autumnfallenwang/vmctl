#!/usr/bin/env python3
"""Minimal traffic driver for the vmctl IG test environment.

Stands in for the only load-balancer function that matters here — spreading
requests across the identical IG hosts — so each host accumulates its own JSON
audit log. vmctl reaches each host directly over SSH; this script only generates
the logs there is something to read.

Round-robins varied request paths across the hosts, tagging each with a unique
X-Correlation-Id (so cross-host correlation can be tested later). stdlib only.

The full engine — replay of a captured corpus, deterministic stress scenarios
(same tx-id on both hosts, clock skew, broken JSON, bursts) — is M02.

Usage:
    python3 drive.py                       # 30 reqs across the two default IG hosts
    python3 drive.py --count 100 --delay 0
    python3 drive.py --hosts 192.168.77.11:9080 192.168.77.12:9080
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

DEFAULT_HOSTS = ["192.168.77.11:9080", "192.168.77.12:9080"]
DEFAULT_PATHS = [
    "/login",
    "/api/orders",
    "/api/orders/42",
    "/health",
    "/route/report",
    "/logout",
]


def build_request(host: str, path: str) -> urllib.request.Request:
    """One request to http://<host><path> with a unique correlation id header."""
    return urllib.request.Request(
        f"http://{host}{path}",
        headers={
            "X-Correlation-Id": uuid.uuid4().hex,
            "User-Agent": "vmctl-drive/0.1",
        },
    )


def drive(
    hosts: list[str],
    paths: list[str],
    count: int,
    delay: float,
    timeout: float,
) -> dict[str, Counter[str]]:
    """Send `count` requests round-robin across `hosts`, cycling through `paths`.

    Returns a per-host tally of response status codes (or "ERR" on failure).
    """
    host_cycle = itertools.cycle(hosts)
    path_cycle = itertools.cycle(paths)
    tally: dict[str, Counter[str]] = {h: Counter() for h in hosts}

    for _ in range(count):
        host = next(host_cycle)
        path = next(path_cycle)
        try:
            with urllib.request.urlopen(build_request(host, path), timeout=timeout) as resp:
                tally[host][str(resp.status)] += 1
        except urllib.error.HTTPError as exc:
            tally[host][str(exc.code)] += 1
        except (urllib.error.URLError, OSError) as exc:
            tally[host]["ERR"] += 1
            print(f"  ! {host}{path}: {exc}", file=sys.stderr)
        if delay:
            time.sleep(delay)

    return tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drive", description=__doc__.splitlines()[0])
    parser.add_argument("--hosts", nargs="+", default=DEFAULT_HOSTS)
    parser.add_argument("--paths", nargs="+", default=DEFAULT_PATHS)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.05, help="seconds between requests")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)

    print(f"driving {args.count} requests round-robin across {args.hosts}")
    tally = drive(args.hosts, args.paths, args.count, args.delay, args.timeout)
    for host, counter in tally.items():
        summary = ", ".join(f"{code}:{n}" for code, n in sorted(counter.items()))
        print(f"  {host} -> {summary or '(no requests)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
