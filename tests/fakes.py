"""In-memory Transport/Connection fakes for fast (no-network) tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from vmctl.transport import CommandResult, Connection, Transport, TransportError


class FakeConnection(Connection):
    def __init__(
        self,
        host: str,
        *,
        run_stdout: Callable[[str], str] | None = None,
        run_error: TransportError | None = None,
        lines: list[str] | None = None,
    ) -> None:
        self.host = host
        self._run_stdout = run_stdout or (lambda _cmd: "")
        self._run_error = run_error
        self._lines = lines or []
        self.closed = False

    async def run(self, cmd: str) -> CommandResult:
        if self._run_error is not None:
            raise self._run_error
        return CommandResult(self.host, 0, self._run_stdout(cmd), "")

    async def stream(self, cmd: str) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def close(self) -> None:
        self.closed = True


class FakeTransport(Transport):
    def __init__(
        self,
        *,
        connect_error_hosts: set[str] | None = None,
        conn_factory: Callable[[str], FakeConnection] | None = None,
    ) -> None:
        self.connect_error_hosts = connect_error_hosts or set()
        self.conn_factory = conn_factory
        self.connections: list[FakeConnection] = []
        self.calls: list[tuple[str, str, str]] = []  # (host, user, password) per connect

    async def connect(
        self, host: str, user: str, password: str, *, connect_timeout: float = 8.0
    ) -> Connection:
        self.calls.append((host, user, password))
        if host in self.connect_error_hosts:
            raise TransportError(host, "connect failed (fake)")
        conn = self.conn_factory(host) if self.conn_factory else FakeConnection(host)
        self.connections.append(conn)
        return conn
