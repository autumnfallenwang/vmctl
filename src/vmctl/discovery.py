"""Remote file discovery: expand each input's globs per host at run time.

Mirrors a log shipper's file discovery (docs/adr/0003, 0005): the rule declares a
glob pattern; the concrete files are found by expanding it *on each host* over SSH,
so routes/files that come and go are picked up automatically and per-host
differences are handled. The set is reported, never silently empty.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch

from vmctl.config import Host, Profile
from vmctl.transport import Transport, TransportError

# Globs come from config (trusted-ish), but we still build a remote shell command
# with them, so restrict to safe glob characters to prevent command injection.
_SAFE_GLOB = re.compile(r"^[A-Za-z0-9._*?/\[\]-]+$")


class DiscoveryError(Exception):
    """Raised for an unsafe glob or base_dir before any remote command is built."""


@dataclass
class MatchedInput:
    type: str
    files: list[str]


@dataclass
class HostDiscovery:
    host: str
    inputs: list[MatchedInput] = field(default_factory=list)
    error: TransportError | None = None


@dataclass
class DiscoveryResult:
    hosts: list[HostDiscovery]

    @property
    def ok(self) -> bool:
        return all(h.error is None for h in self.hosts)


def build_glob_command(base_dir: str, paths: list[str]) -> str:
    """A remote bash command that prints (relative) files matching `paths` under
    `base_dir`, one per line. Unmatched globs expand to nothing (`nullglob`)."""
    if "'" in base_dir:
        raise DiscoveryError(f"base_dir may not contain a single quote: {base_dir!r}")
    for pat in paths:
        if not _SAFE_GLOB.match(pat):
            raise DiscoveryError(f"unsafe glob pattern: {pat!r}")
    globs = " ".join(paths)  # unquoted so the remote shell expands them
    return f"cd '{base_dir}' 2>/dev/null && shopt -s nullglob && printf '%s\\n' {globs}"


def apply_excludes(files: list[str], excludes: list[str]) -> list[str]:
    """Drop files matching any exclude glob (client-side, fnmatch on the relative path)."""
    return [f for f in files if not any(fnmatch(f, ex) for ex in excludes)]


async def discover(
    transport: Transport,
    profile: Profile,
    fallback_password: str | None = None,
    *,
    connect_timeout: float = 8.0,
) -> DiscoveryResult:
    """For every host, expand each input's globs and return the matched files.

    Each host authenticates with its inline ``password`` if set, else
    ``fallback_password``. Hosts are contacted concurrently; one failing host (or one
    with no password available) does not affect the others."""
    base_dir = profile.base_dir or "."

    async def one_host(host: Host) -> HostDiscovery:
        password = host.password or fallback_password
        if password is None:
            return HostDiscovery(
                host.host,
                error=TransportError(host.host, "no password (set one in config, env, or prompt)"),
            )
        try:
            conn = await transport.connect(
                host.host, host.user, password, connect_timeout=connect_timeout
            )
        except TransportError as exc:
            return HostDiscovery(host.host, error=exc)
        try:
            matched: list[MatchedInput] = []
            for inp in profile.inputs:
                cmd = build_glob_command(base_dir, inp.path)
                result = await conn.run(cmd)
                files = [line for line in result.stdout.splitlines() if line]
                matched.append(MatchedInput(inp.type, apply_excludes(files, inp.exclude)))
            return HostDiscovery(host.host, inputs=matched)
        except TransportError as exc:
            return HostDiscovery(host.host, error=exc)
        finally:
            await conn.close()

    hosts = await asyncio.gather(*(one_host(h) for h in profile.hosts))
    return DiscoveryResult(list(hosts))
