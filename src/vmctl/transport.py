"""SSH transport: reach hosts, run commands, stream output, fan out concurrently.

Agentless — vmctl runs remote base-tool commands (`find`, `tail -F`, `grep`, ...)
over SSH and reads the results (docs/adr/0006). The `Transport` / `Connection`
interfaces are abstract so tests can substitute a fake; `AsyncSSHTransport` is the
real implementation.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import asyncssh

if TYPE_CHECKING:
    from vmctl.config import Host


class TransportError(Exception):
    """A per-host connect / auth / exec failure. Carries the host for reporting."""

    def __init__(self, host: str, message: str) -> None:
        self.host = host
        super().__init__(f"{host}: {message}")


@dataclass
class CommandResult:
    host: str
    exit_status: int
    stdout: str
    stderr: str


class Connection(ABC):
    """A live connection to one host."""

    host: str

    @abstractmethod
    async def run(self, cmd: str) -> CommandResult:
        """Run a command to completion."""

    @abstractmethod
    def stream(self, cmd: str) -> AsyncIterator[str]:
        """Run a long-lived command, yielding stdout lines as they arrive (for `tail`)."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""


class Transport(ABC):
    """Opens connections to hosts."""

    @abstractmethod
    async def connect(
        self, host: str, user: str, password: str, *, connect_timeout: float = 8.0
    ) -> Connection:
        """Open a password-authenticated connection to a host."""


class AsyncSSHConnection(Connection):
    def __init__(self, host: str, conn: asyncssh.SSHClientConnection) -> None:
        self.host = host
        self._conn = conn

    async def run(self, cmd: str) -> CommandResult:
        try:
            result = await self._conn.run(cmd, check=False)
        except (asyncssh.Error, OSError) as exc:
            raise TransportError(self.host, f"command failed: {exc}") from exc
        return CommandResult(
            host=self.host,
            exit_status=result.exit_status if result.exit_status is not None else -1,
            stdout=_as_text(result.stdout),
            stderr=_as_text(result.stderr),
        )

    async def stream(self, cmd: str) -> AsyncIterator[str]:
        try:
            proc = await self._conn.create_process(cmd)
        except (asyncssh.Error, OSError) as exc:
            raise TransportError(self.host, f"stream failed: {exc}") from exc
        try:
            async for line in proc.stdout:
                yield str(line).rstrip("\n")
        finally:
            proc.close()
            await proc.wait_closed()

    async def close(self) -> None:
        self._conn.close()
        await self._conn.wait_closed()


class AsyncSSHTransport(Transport):
    async def connect(
        self, host: str, user: str, password: str, *, connect_timeout: float = 8.0
    ) -> Connection:
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host,
                    username=user,
                    password=password,
                    known_hosts=None,  # isolated NAT lab; real known_hosts is a M06 hardening item
                ),
                timeout=connect_timeout,
            )
        except (asyncssh.Error, OSError, asyncio.TimeoutError) as exc:
            # Some failures (notably a timeout) carry an empty message — fall back to the
            # exception type so the error is never a bare "connect failed:". Test str(exc),
            # not exc: the exception object is always truthy even when its message is empty.
            detail = str(exc) or type(exc).__name__
            raise TransportError(host, f"connect failed: {detail}") from exc
        return AsyncSSHConnection(host, conn)


@dataclass
class HostOutcome:
    host: str
    result: CommandResult | None
    error: TransportError | None


async def run_on_hosts(
    transport: Transport,
    hosts: list[Host],
    fallback_password: str | None,
    cmd: str,
    *,
    connect_timeout: float = 8.0,
) -> list[HostOutcome]:
    """Run one command on every host concurrently. Each host uses its inline
    ``password`` if set, else ``fallback_password``. One host failing does not affect
    the others — each host yields either a result or an error."""

    async def one(host: Host) -> HostOutcome:
        password = host.password or fallback_password
        if password is None:
            return HostOutcome(host.host, None, TransportError(host.host, "no password available"))
        try:
            conn = await transport.connect(
                host.host, host.user, password, connect_timeout=connect_timeout
            )
        except TransportError as exc:
            return HostOutcome(host.host, None, exc)
        try:
            return HostOutcome(host.host, await conn.run(cmd), None)
        except TransportError as exc:
            return HostOutcome(host.host, None, exc)
        finally:
            await conn.close()

    return list(await asyncio.gather(*(one(h) for h in hosts)))


def _as_text(data: object) -> str:
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data if isinstance(data, str) else ""
