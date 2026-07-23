---
milestone: 4
title: tail command (live stream)
status: planned
started: TBD
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

- [ ] `vmctl tail test_ig` follows both `ig1` and `ig2` live.
- [ ] Driving traffic with `testenv/engine/drive.py` produces merged ECS events streaming to terminal (and to `--file`).
- [ ] `--type`/`--rule` narrows to a single logset; per-host origin is visible in the output.
- [ ] A host dropping mid-stream reconnects (or is reported) without killing the run.
- [ ] A `@pytest.mark.integration` test drives traffic and asserts events arrive from both hosts; check loop green.

## Non-goals (this milestone)
- `search` / KQL / pushdown (→ M05).
- Exactly-once / resume (→ M07); `tail -F` is best-effort live follow.

## Progress

- (not started)
