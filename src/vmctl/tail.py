"""`tail` mode: stream logs live across a profile's hosts (docs/adr/0005).

Per host: connect once, glob each input's files, and run one ``tail -F`` per file
(so each line's source file — hence `log.file.path` and the filename `route_id` — is
known). Every stream frames with its input's codec and assembles ECS events; all
streams merge through one queue to a single writer.

`start_position` is not yet honoured (always starts at end); reconnect/rotation
resilience is track D.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

from vmctl.codecs import make_codec
from vmctl.config import Host, Input, Profile
from vmctl.discovery import apply_excludes, build_glob_command
from vmctl.event import assemble
from vmctl.transport import Connection, Transport, TransportError

_SENTINEL = object()
_RECONNECT_CAP = 30.0


def _remote_path(base_dir: str, rel: str) -> str:
    path = rel if base_dir in ("", ".") else f"{base_dir.rstrip('/')}/{rel}"
    if "'" in path:
        raise ValueError(f"refusing to tail a path containing a single quote: {path!r}")
    return path


async def stream_file_events(
    conn: Connection,
    *,
    host: str,
    profile: Profile,
    inp: Input,
    file_path: str,
) -> AsyncIterator[dict[str, Any]]:
    """Tail one file and yield ECS events. Runs until the stream ends or is cancelled."""
    codec = make_codec(inp.codec)

    def _events(frames: list[Any]) -> list[dict[str, Any]]:
        return [
            assemble(
                f,
                host=host,
                profile=profile.name,
                inp=inp,
                file_path=file_path,
                filters=profile.filters,
            )
            for f in frames
        ]

    async for line in conn.stream(_tail_cmd(file_path, inp.start_position)):
        for event in _events(codec.feed(line)):
            yield event
    # Stream ended (disconnect) — flush any buffered multiline event.
    for event in _events(codec.flush()):
        yield event


def _tail_cmd(file_path: str, start_position: str) -> str:
    # `beginning` replays the whole file then follows; `end` only new lines.
    start = "+1" if start_position == "beginning" else "0"
    return f"tail -n {start} -F '{file_path}'"


async def run_tail(
    transport: Transport,
    profile: Profile,
    *,
    fallback_password: str | None,
    type_filter: str | None,
    write: Callable[[dict[str, Any]], None],
    report_error: Callable[[str], None] = lambda _m: None,
    max_reconnects: int | None = None,
    reconnect_base: float = 1.0,
) -> int:
    """Stream all matching inputs across all hosts to `write`, reconnecting on drop.

    Runs until cancelled (Ctrl-C). Each host reconnects with exponential backoff after
    a dropped connection (unlimited by default; `max_reconnects` bounds it). Returns 1
    if any host permanently failed (bad password, or gave up), else 0.
    """
    inputs = [i for i in profile.inputs if type_filter is None or i.type == type_filter]
    if type_filter is not None and not inputs:
        report_error(f"no input of type '{type_filter}' in profile '{profile.name}'")
        return 1

    queue: asyncio.Queue[Any] = asyncio.Queue()
    had_error = False

    async def pump(gen: AsyncIterator[dict[str, Any]]) -> None:
        async for event in gen:
            await queue.put(event)

    async def tail_session(conn: Connection, host_name: str) -> None:
        """Glob each input's files on `conn` and tail them until a stream ends/drops."""
        tasks: list[asyncio.Task[None]] = []
        for inp in inputs:
            result = await conn.run(build_glob_command(profile.base_dir or ".", inp.path))
            files = apply_excludes([ln for ln in result.stdout.splitlines() if ln], inp.exclude)
            for rel in files:
                gen = stream_file_events(
                    conn,
                    host=host_name,
                    profile=profile,
                    inp=inp,
                    file_path=_remote_path(profile.base_dir or ".", rel),
                )
                tasks.append(asyncio.create_task(pump(gen)))
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
            except TransportError as exc:
                report_error(f"{host.host}: {exc}")
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
        await asyncio.gather(*(host_worker(h) for h in profile.hosts))
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
