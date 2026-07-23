---
milestone: 7
title: Resumable collection (offset registry)
status: planned
started: TBD
---

# M07 — Resumable collection (offset registry) — optional / stretch

Add exactly-once, resumable collection so `search`/collection can "pick up where it
left off" without re-reading or missing lines — the client-side equivalent of a
shipper's sincedb/registry. **Explicitly optional** per
[ADR 0005](../adr/0005-collection-and-search-execution.md); v1 (`tail -F` + `grep`)
works without it. See [ROADMAP.md](ROADMAP.md).

## Scope

### A. Client-side sincedb
- Persist `(host, file-identity, offset)` on the operator machine, keyed by a stable file identity (`stat` inode + device + size), with expiry to survive inode recycling.

### B. Incremental read + resume
- Read from the last offset (`tail -c +offset` / `dd skip`); advance only after successful consume; detect rotation (inode changed / size shrank) and hand off cleanly.
- Dedup across rotations so nothing is re-emitted or dropped.

## Exit criteria

- [ ] A repeated collection over the same sources resumes from the last offset — no re-read, no missed lines.
- [ ] Rotation during collection is handled without loss or duplication.
- [ ] Strictly opt-in; default behaviour (M04/M05) is unchanged when the registry is off.
- [ ] Unit tests for offset/rotation logic; a marked integration test against the live VMs.

## Non-goals (this milestone)
- Any change to `tail`/`search` semantics when the registry is disabled.

## Progress

- (not started)
