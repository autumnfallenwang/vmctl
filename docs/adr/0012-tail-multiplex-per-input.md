# 0012 — `tail` concurrency: multiplex one `tail -F` per input

- **Status:** accepted
- **Date:** 2026-07-24
- **Deciders:** Aaron Wang

## Context

`tail` opens one SSH channel **per matched file** (`conn.stream` → asyncssh `create_process`), all
concurrent on the single connection vmctl holds per host. OpenSSH's default `MaxSessions` is 10 per
connection, so any input matching more files than that fails outright (`stream failed: open
failed`). Real deployments blow past it immediately — an IG host carries ~67 per-route logs and ~99
audit dirs (M12 finding #2).

M12 shipped a stopgap: a profile-level `max_concurrent_files` (default 8) that refuses an over-cap
host with one clear, actionable error instead of N cryptic per-channel failures. That makes the
failure *clean* but doesn't make `tail` *work*, and the escape hatch — raising sshd's `MaxSessions`
— is frequently not permitted on locked-down RHEL.

Constraints in play: nothing may be installed on the remote hosts (base utilities only); each
streamed line must stay attributable to its source file (`log.file.path` and the filename-derived
`route_id`); and each file's codec — `multiline` especially — is **stateful per file**.

## Decision

**Multiplex per input:** run one `tail -n N -F f1 f2 … fk` per **input** covering all that input's
matched files, route each line to its source using the `==> <path> <==` header GNU `tail` prints on
a file switch, and keep one codec instance per file. Channels per host drop from Σfiles (67+) to
**#inputs** (typically 1–5). Optional per-input chunking stays available as a safety valve.

Options rejected:

- **Multi-connection** (⌈files/cap⌉ SSH connections per host, channels spread across them). Trades a
  channel-count problem for a connection-count problem: ~9–20 concurrent SSH auths per host with
  rotating passwords, and it destroys the clean one-connection-per-host invariant — every connection
  then needs its own drop/reconnect/re-partition logic.
- **One `tail` per host.** Can't express differing `start_position` across inputs (`-n +1` vs `-n 0`
  cannot coexist in one command). Per-*input* is the natural boundary: one `start_position`, one
  codec spec.
- **`find | xargs tail` / hand-rolled remote read loop.** Mixes files of different codecs into one
  stream, and the latter throws away `tail -F`'s inotify-based rotation handling.

**Empirical basis** (GNU coreutils, verified locally): the header is exactly `==> <path> <==` with
the verbatim command-line argument; it is emitted **only on a switch**, not per line (so a
"current file" pointer is required); every header but the first is preceded by a **blank separator
line that is not file content** (needs one-line lookahead); a **single-file** `tail` prints **no**
header (pre-assign the current file); and all rotation/truncation/cannot-open diagnostics go to
**stderr**, which `transport.stream()` never reads — so the event stream stays clean.

## Consequences

- **Easier:** `tail` works at real deployment scale with **no sshd or remote change**; channel count
  is bounded by input count regardless of how many files match; fewer inotify instances than today.
- **Harder / to live with:** `tail.py` gains a header-routing parser (current-file pointer,
  blank-separator lookahead, per-file codec dict, flush-all on stream end). A log line whose literal
  content equals `==> <watched path> <==` could spoof a header — mitigated by honouring a header
  only when its path is in the known set passed to that `tail`; residual risk is negligible for
  ForgeRock logs but is real.
- `max_concurrent_files` is **re-purposed** from a per-file cap into a per-input chunk size /
  channel-count guard; `_TooManyFiles` relaxes to fire only on a channel-count breach.
- **Unchanged:** per-file codec state and per-file attribution. Carrying a partial multiline event
  across a log rotation is imperfect *today* as well (both designs use `tail -F`), so this is not a
  regression.
- **Risk to track:** Rocky 9 ships coreutils **8.32**; the behaviour above was verified on 9.11. The
  header/separator/startup behaviour **must be confirmed on the lab host before shipping** — it is a
  gating exit criterion in [milestone 13](../milestones/13-scaling-followups.md). If it differs,
  revisit this decision.

## Notes

- From M12 finding #2 ([milestone 12](../milestones/12-field-findings-fixes.md)); implementation is
  scoped in [milestone 13](../milestones/13-scaling-followups.md).
- Relates to [ADR 0006](./0006-runtime-transport-asyncssh.md) (asyncssh transport, one connection
  per host) and [ADR 0003](./0003-log-source-config-model.md) (inputs and codecs).
