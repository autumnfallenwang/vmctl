"""`tail` mode: stream logs live across a profile's hosts (docs/adr/0005).

Per host: connect once, glob each input's files, and run **one ``tail -F`` per input**
covering all that input's files (docs/adr/0012). GNU tail prints a ``==> path <==``
header when its output switches files, so each line stays attributable to its source —
hence `log.file.path` and the filename `route_id` — while the channel count per host
stays at #inputs instead of #files, clearing SSH's ``MaxSessions`` limit. Every stream
frames with its input's codec (one instance **per file**) and assembles ECS events; all
streams merge through one queue to a single writer.

`start_position` selects whether files are replayed from the top or followed from the
end; a dropped connection reconnects with exponential backoff, and rotation is followed
inherently by ``tail -F`` (its notices go to stderr, which we never read).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from vmctl.codecs import make_codec
from vmctl.config import Host, Input, Profile
from vmctl.discovery import apply_excludes, build_glob_command
from vmctl.event import assemble
from vmctl.transport import Connection, Transport, TransportError

_SENTINEL = object()
_RECONNECT_CAP = 30.0
# Only to stay clear of ARG_MAX on a pathological glob; real profiles yield one chunk
# per input, so channels ≈ #inputs.
_FILES_PER_TAIL = 500
_HEADER = re.compile(r"^==> (.*) <==$")


class _TooManyFiles(Exception):
    """A host needs more tail channels than `max_concurrent_files`. Permanent — no reconnect."""


def _parse_header(line: str, known: set[str]) -> str | None:
    """The path from a ``==> path <==`` switch header, iff it names a file we asked this
    tail to follow. The known-set check is the spoof guard: a log line whose literal text
    looks like a header cannot redirect attribution to an arbitrary path."""
    match = _HEADER.match(line)
    if match is None:
        return None
    path = match.group(1)
    return path if path in known else None


def _remote_path(base_dir: str, rel: str) -> str:
    # An absolute glob is already absolute; joining base_dir doubles it into a
    # nonexistent path (M12 bug #1). Only relative discoveries get base_dir prepended.
    if rel.startswith("/") or base_dir in ("", "."):
        path = rel
    else:
        path = f"{base_dir.rstrip('/')}/{rel}"
    if "'" in path:
        raise ValueError(f"refusing to tail a path containing a single quote: {path!r}")
    return path


async def stream_input_events(
    conn: Connection,
    *,
    host: str,
    profile: Profile,
    inp: Input,
    file_paths: list[str],
) -> AsyncIterator[dict[str, Any]]:
    """Tail all of one input's files over a SINGLE channel and yield ECS events.

    Routing follows the behaviour verified on the target (docs/adr/0012): tail emits a
    ``==> path <==`` header only when its output *switches* files, so we hold a `current`
    pointer and route every following line to that file's own codec. Each header but the
    first is preceded by a blank line that is tail's separator, not file content — held
    back by one line of lookahead. A single-file tail prints no header at all, so
    `current` is pre-assigned in that case. Runs until the stream ends or is cancelled.
    """
    codecs = {path: make_codec(inp.codec) for path in file_paths}
    known = set(file_paths)
    current = file_paths[0] if len(file_paths) == 1 else None
    pending_blank = False

    def _events(path: str, frames: list[Any]) -> list[dict[str, Any]]:
        return [
            assemble(
                f,
                host=host,
                profile=profile.name,
                inp=inp,
                file_path=path,
                filters=profile.filters,
            )
            for f in frames
        ]

    async for line in conn.stream(_tail_cmd_multi(file_paths, inp.start_position)):
        header = _parse_header(line, known)
        if header is not None:
            pending_blank = False  # the held blank was tail's separator — drop it
            current = header
            continue
        if current is None:
            current = file_paths[0]  # defensive: content before any header
        if line == "":
            # Can't yet tell a separator from real content. Hold it; two blanks in a row
            # means the first one was content.
            if pending_blank:
                for event in _events(current, codecs[current].feed("")):
                    yield event
            pending_blank = True
            continue
        if pending_blank:
            pending_blank = False
            for event in _events(current, codecs[current].feed("")):
                yield event
        for event in _events(current, codecs[current].feed(line)):
            yield event

    # Stream ended (disconnect) — flush every file's buffered multiline event.
    for path, codec in codecs.items():
        for event in _events(path, codec.flush()):
            yield event


def _tail_cmd_multi(file_paths: list[str], start_position: str) -> str:
    # `beginning` replays each file then follows; `end` only new lines. Paths are already
    # single-quote-free (`_remote_path` refuses them), so plain quoting is safe.
    start = "+1" if start_position == "beginning" else "0"
    quoted = " ".join(f"'{p}'" for p in file_paths)
    return f"tail -n {start} -F {quoted}"


async def run_tail(
    transport: Transport,
    profile: Profile,
    *,
    fallback_password: str | None,
    type_filter: str | None,
    host_filter: set[str] | None = None,
    write: Callable[[dict[str, Any]], None],
    report_error: Callable[[str], None] = lambda _m: None,
    max_reconnects: int | None = None,
    reconnect_base: float = 1.0,
) -> int:
    """Stream all matching inputs across all hosts to `write`, reconnecting on drop.

    Runs until cancelled (Ctrl-C). Each host reconnects with exponential backoff after
    a dropped connection (unlimited by default; `max_reconnects` bounds it). `host_filter`
    narrows the run to named hosts. Returns 1 if any host permanently failed (bad password,
    gave up, or matched more files than `max_concurrent_files`), else 0.
    """
    inputs = [i for i in profile.inputs if type_filter is None or i.type == type_filter]
    if type_filter is not None and not inputs:
        report_error(f"no input of type '{type_filter}' in profile '{profile.name}'")
        return 1
    if host_filter is not None:
        known = {h.host for h in profile.hosts}
        unknown = host_filter - known
        if unknown:
            report_error(
                f"unknown host(s) {sorted(unknown)} in profile '{profile.name}'; "
                f"known: {sorted(known)}"
            )
            return 1
    hosts = [h for h in profile.hosts if host_filter is None or h.host in host_filter]

    queue: asyncio.Queue[Any] = asyncio.Queue()
    had_error = False

    async def pump(gen: AsyncIterator[dict[str, Any]]) -> None:
        async for event in gen:
            await queue.put(event)

    async def tail_session(conn: Connection, host_name: str) -> None:
        """Glob each input's files on `conn` and tail them until a stream ends/drops.

        One channel per input, not per file (docs/adr/0012) — a `tail -F` never completes,
        so a semaphore would starve later files; multiplexing is what actually keeps the
        channel count under SSH's `MaxSessions`. `max_concurrent_files` now bounds those
        channels: over it, refuse the host with one clear error rather than letting the
        extra channels fail cryptically one by one.
        """
        groups: list[tuple[Input, list[str]]] = []
        for inp in inputs:
            result = await conn.run(build_glob_command(profile.base_dir or ".", inp.path))
            files = apply_excludes([ln for ln in result.stdout.splitlines() if ln], inp.exclude)
            paths = [_remote_path(profile.base_dir or ".", rel) for rel in files]
            for start in range(0, len(paths), _FILES_PER_TAIL):
                groups.append((inp, paths[start : start + _FILES_PER_TAIL]))

        cap = profile.max_concurrent_files
        if len(groups) > cap:
            raise _TooManyFiles(
                f"{host_name}: needs {len(groups)} tail channels but max_concurrent_files={cap} "
                f"(SSH caps concurrent sessions at MaxSessions, default 10) — narrow "
                f"--type/--host, or raise max_concurrent_files in the profile and MaxSessions "
                f"on the host"
            )

        tasks = [
            asyncio.create_task(
                pump(
                    stream_input_events(
                        conn, host=host_name, profile=profile, inp=inp, file_paths=paths
                    )
                )
            )
            for inp, paths in groups
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def host_worker(host: Host) -> None:
        nonlocal had_error
        password = host.password or fallback_password
        if password is None:
            had_error = True
            report_error(f"{host.host}: no password available")
            return

        backoff = reconnect_base
        attempt = 0
        while True:
            conn: Connection | None = None
            try:
                conn = await transport.connect(host.host, host.user, password)
                backoff = reconnect_base  # reset after a successful connect
                await tail_session(conn, host.host)
                return  # all streams ended cleanly (not a drop) — this host is done
            except _TooManyFiles as exc:
                had_error = True
                report_error(str(exc))  # message already carries the host name
                return  # permanent — reconnecting cannot help
            except TransportError as exc:
                report_error(str(exc))  # TransportError already carries the host name
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close()

            # Reached only after a dropped connection (TransportError).
            attempt += 1
            if max_reconnects is not None and attempt > max_reconnects:
                had_error = True
                report_error(f"{host.host}: giving up after {attempt - 1} reconnect(s)")
                return
            report_error(f"{host.host}: connection lost, reconnecting (attempt {attempt})")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_CAP) if backoff > 0 else 0.0

    async def produce_all() -> None:
        await asyncio.gather(*(host_worker(h) for h in hosts))
        await queue.put(_SENTINEL)

    producer = asyncio.create_task(produce_all())
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            write(item)
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer

    return 1 if had_error else 0
