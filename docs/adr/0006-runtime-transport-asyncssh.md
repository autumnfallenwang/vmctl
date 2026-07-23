# 0006 — Runtime transport: asyncssh (async core)

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder (decision delegated; researched by Claude)

## Context

vmctl's runtime spine is: connect to N hosts over SSH with **password auth**, run remote base-tool commands (`tail -F`, `grep`, `awk`), **stream** their stdout, and **merge / fan out** across hosts. This ADR picks the SSH transport and the runtime model it implies. Candidates researched: paramiko, asyncssh, parallel-ssh, fabric.

## Decision

**Transport: `asyncssh`. vmctl's core is async (`asyncio`).**

vmctl's workload — maintain many long-lived `tail -F` streams and merge them, plus fan out bounded `search` reads — is a textbook async-I/O problem (many mostly-idle connections in one event loop). asyncssh fits it best:

- **Async-native, best multi-host performance** (~15× faster than the slowest in published benchmarks); no manual thread pool.
- **Native password auth** — our requirement.
- **Streaming fits exactly:** `conn.create_process()` + `await proc.stdout.readline()` = "`tail -F`, lines as they arrive"; `asyncio.gather()` merges N hosts. The hardest part of `tail` mode (merging live streams) becomes trivial in async.
- **Minimal, pip-friendly deps:** only `cryptography` (PyCA), which ships manylinux wheels — honors the plain-venv/pip install constraint ([0001](./0001-initial-stack.md)).
- **Python 3.10+** — under our 3.12 floor.

**Rejected:**
- **paramiko** — synchronous; forces thread-per-host + a manual merge queue, exactly the plumbing async removes. (Fine library, wrong shape for our stream-merge core.)
- **parallel-ssh** — fast but built on a C/libssh2 extension (`ssh2-python`), adding install fragility for speed we don't need at our scale.
- **fabric** — multiprocessing per host (file-descriptor limits), oriented at short tasks, poor fit for long-lived streams.

**License:** asyncssh is `EPL-2.0 OR GPL-2.0-or-later`. As an **unmodified dependency**, EPL-2.0 does not constrain vmctl's own license or distribution; we elect EPL-2.0 (no GPL contamination). Acceptable.

**Implied picks:**
- **Runtime:** stdlib `asyncio`; the CLI wraps `asyncio.run()`. The transport sits behind a small `Transport` interface so shelling out to `ssh` or swapping paramiko stays possible.
- **Config YAML parser:** `pyyaml` (stdlib has none; pip-friendly).
- **CLI:** stdlib `argparse` for now (zero-dep); revisit click/typer only if UX demands.
- **KQL:** a small hand-rolled subset parser (no suitable library) — later.

First real runtime dependencies (was `[]`): illustratively `dependencies = ["asyncssh>=2.14", "pyyaml>=6"]`; exact pins set at build.

## Consequences

- **Positive:** the hardest part (merging N live streams) is natural in async; password auth native; fast fan-out; minimal deps that install cleanly via pip; clean, terse streaming API.
- **Costs:** the codebase commits to an **async paradigm**; two new runtime deps (`asyncssh`+`cryptography`, `pyyaml`); an EPL-licensed dependency (assessed acceptable).
- **Reversible:** the `Transport` interface isolates asyncssh, so a later switch to shell-`ssh` or paramiko is contained.

## Notes

- Decision delegated to Claude and based on web research comparing asyncssh with paramiko, parallel-ssh, and fabric.
- Builds on [0001](./0001-initial-stack.md) (Python 3.12, pip/venv) and serves the `tail`/`search` execution model in [0005](./0005-collection-and-search-execution.md).
