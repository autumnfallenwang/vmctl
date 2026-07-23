"""`search` mode: bounded historical read + KQL across a profile's hosts (docs/adr/0005).

The read-mode counterpart to `tail`, and the place the three tiers meet:

1. **Planner** (`vmctl.planner`) drops hosts, inputs and files a query can't match — before
   connecting, before globbing, before reading.
2. **Pushdown** (`vmctl.pushdown`) turns the time window and safe literal terms into a
   remote `awk`/`grep`, so only candidate bytes cross the wire. A sound superset.
3. **Exact evaluation** (`vmctl.query`) decides every result, over fully-assembled ECS
   events. Tiers 1 and 2 only ever narrow what tier 3 is given.

Only matching events are buffered, then emitted in `@timestamp` order so a multi-host
result set reads chronologically.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from vmctl import planner
from vmctl.codecs import frame_lines, make_codec
from vmctl.config import Host, Input, Profile
from vmctl.discovery import apply_excludes, build_glob_command
from vmctl.event import assemble
from vmctl.predicate import Node
from vmctl.pushdown import Window, build_read_command, pushable_terms, window_from_query
from vmctl.query import matches
from vmctl.transport import Connection, Transport, TransportError


def _remote_path(base_dir: str, rel: str) -> str:
    path = rel if base_dir in ("", ".") else f"{base_dir.rstrip('/')}/{rel}"
    if "'" in path:
        raise ValueError(f"refusing to read a path containing a single quote: {path!r}")
    return path


async def run_search(
    transport: Transport,
    profile: Profile,
    *,
    query: Node,
    fallback_password: str | None,
    type_filter: str | None = None,
    write: Callable[[dict[str, Any]], None],
    report_error: Callable[[str], None] = lambda _m: None,
    no_pushdown: bool = False,
) -> int:
    """Search every matching input across the profile's hosts. Returns 1 if a host failed.

    The time window comes from `@timestamp` range predicates inside `query` — the filter
    carries its own bounds. `no_pushdown` forces a full `cat` scan with no remote
    filtering, the baseline a pushed-down run is compared against to prove soundness.
    """
    inputs = [i for i in profile.inputs if type_filter is None or i.type == type_filter]
    if type_filter is not None and not inputs:
        report_error(f"no input of type '{type_filter}' in profile '{profile.name}'")
        return 1

    window = Window() if no_pushdown else window_from_query(query)
    base_dir = profile.base_dir or "."
    results: list[dict[str, Any]] = []
    scanned: list[str] = []
    had_error = False

    async def read_file(conn: Connection, host: str, inp: Input, file_path: str) -> None:
        terms = [] if no_pushdown else pushable_terms(query, codec_name=inp.codec.name)
        outcome = await conn.run(
            build_read_command(file_path, codec_name=inp.codec.name, window=window, terms=terms)
        )
        scanned.append(f"{host}:{file_path}")
        codec = make_codec(inp.codec)
        for frame in frame_lines(codec, outcome.stdout.splitlines()):
            event = assemble(
                frame,
                host=host,
                profile=profile.name,
                inp=inp,
                file_path=file_path,
                filters=profile.filters,
            )
            if matches(query, event):
                results.append(event)

    async def host_worker(host: Host) -> None:
        nonlocal had_error
        if not planner.host_survives(query, host=host.host, profile=profile.name):
            return  # tier 1: the query can't match anything on this host
        password = host.password or fallback_password
        if password is None:
            had_error = True
            report_error(f"{host.host}: no password available")
            return

        conn: Connection | None = None
        try:
            conn = await transport.connect(host.host, host.user, password)
            for inp in inputs:
                if not planner.input_survives(
                    query, host=host.host, profile=profile.name, inp=inp
                ):
                    continue
                globbed = await conn.run(build_glob_command(base_dir, inp.path))
                files = apply_excludes(
                    [ln for ln in globbed.stdout.splitlines() if ln], inp.exclude
                )
                for rel in files:
                    file_path = _remote_path(base_dir, rel)
                    if not planner.file_survives(
                        query,
                        host=host.host,
                        profile=profile.name,
                        inp=inp,
                        file_path=file_path,
                        filters=profile.filters,
                    ):
                        continue
                    await read_file(conn, host.host, inp, file_path)
        except TransportError as exc:
            had_error = True
            report_error(str(exc))  # TransportError already carries the host name
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.close()

    await asyncio.gather(*(host_worker(h) for h in profile.hosts))

    results.sort(key=lambda e: str(e.get("@timestamp", "")))
    for event in results:
        write(event)

    report_error(f"scanned {len(scanned)} file(s); {len(results)} match(es)")
    return 1 if had_error else 0
