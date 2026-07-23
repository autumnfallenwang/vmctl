---
milestone: 4
title: tail command (live stream)
status: done
started: 2026-07-23
---

# M04 — `tail` command (live stream)

The first user-facing capability: `vmctl tail <profile>` follows the logs across a
deployment's hosts and streams merged ECS events. Wires together M02 (transport) and
M03 (framing + envelope); implements the tail mode of
[ADR 0005](../adr/0005-collection-and-search-execution.md). See [ROADMAP.md](ROADMAP.md).

## Scope

### A. CLI
- `vmctl tail <profile> [--type T | --rule R] [--output ndjson|human] [--file PATH]` (argparse).

### B. Per-host/per-rule streaming (`mode: tail`)
- For each host × rule: remote `tail -F <matched files>` via the transport → codec framing (M03) → ECS envelope (M03).

### C. Merge
- Merge the N host streams into one output via an asyncio queue; each event already carries `host.name` / `labels.*` so per-host origin is clear.

### D. Resilience
- Reconnect on a dropped connection; rotation is followed by `tail -F`; clean shutdown on Ctrl-C; one host failing doesn't stop the others.

## Exit criteria

- [x] `vmctl tail test_ig` follows both `ig1` and `ig2` live.
- [x] Driving traffic with `testenv/engine/drive.py` produces merged ECS events streaming to terminal (and to `--file`).
- [x] `--type` narrows to a single logset; per-host origin is visible in the output.
- [x] A host dropping mid-stream reconnects (or is reported) without killing the run.
- [x] A `@pytest.mark.integration` test drives traffic and asserts events arrive from both hosts; check loop green.

## Non-goals (this milestone)
- `search` / KQL / pushdown (→ M05).
- Exactly-once / resume (→ M07); `tail -F` is best-effort live follow.

## Progress

- 2026-07-23: Milestone opened.
- 2026-07-23: Tracks A+B (+ the queue merge) shipped — `tail.py` (`stream_file_events`: one `tail -F` per file → codec → ECS; `run_tail`: per-host connect + glob + fan-out, asyncio.Queue merge to one writer, per-host error isolation) and the `vmctl tail` CLI (`--type`/`--output`/`--file`). 7 tests + a live integration test. **Verified live**: `vmctl tail test_ig --type ig-audit` streamed merged events from both VMs (40 each) while driving traffic. Remaining for M04: track D — mid-stream reconnect, rotation edges, honoring `start_position`, robust Ctrl-C.
- 2026-07-23: Tracks C+D shipped — track C (queue merge + per-host labelling) was already in A+B; added D: **reconnect on drop** with exponential backoff (unlimited by default, `max_reconnects` bounds it; a clean stream end = done, only a `TransportError` reconnects), `start_position` honoured (`tail -n +1` vs `-n 0`), and cancellation-safe shutdown. Rotation is followed inherently by `tail -F`. 3 new tests (60 fast total); live integration still green. **All M04 exit criteria met.**

## Outcome

Shipped `vmctl tail` — a resilient, live, multi-host merged log stream. `tail.py` runs one `tail -F` per file over asyncssh (so each line keeps its `log.file.path`/`route_id`), frames + assembles ECS events, and merges all streams through one queue to a single writer; hosts reconnect on drop with backoff, and per-host failures are isolated. CLI: `vmctl tail <profile> [--type] [--output human|ndjson] [--file]`. Verified live against both VMs while driving traffic.

Deviations: the queue merge (track C) landed in A+B to make `tail` runnable. Lesson worth caching: distinguish a clean stream end (done) from a dropped connection (reconnect) — infinite-retry-on-any-end hangs on finite streams.

Closed: 2026-07-23
