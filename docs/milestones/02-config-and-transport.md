---
milestone: 2
title: Config & transport foundation
status: active
started: 2026-07-22
---

# M02 — Config & transport foundation

Build the plumbing every later milestone needs: load the profile/rules config and
reach the hosts over SSH. No product feature ships here — the deliverable is "vmctl
can read a profile, connect to its hosts by password, and list the files each rule
matches." Implements [ADR 0003](../adr/0003-log-source-config-model.md) (config
parsing) and [ADR 0006](../adr/0006-runtime-transport-asyncssh.md) (transport). See
[ROADMAP.md](ROADMAP.md) for how this fits the whole build.

## Scope

### A. Config models + loader (ADR 0003)
- Typed models for `profile` (hosts, base_dir, rules) and `rule` (`path`, `exclude`, `start_position`, `mode`, `codec` + `delimiter`, `type`, `tags`, `filters`).
- `pyyaml` loader → models; **validation with clear errors** (unknown keys, bad codec, missing path).
- Decide config file resolution (`--config PATH`, else a default location).

### B. Transport (ADR 0006)
- A small `Transport` interface (async): `connect(host, user, password)`, `run(cmd) -> result`, `stream(cmd) -> async line iterator`, `close()`.
- `asyncssh` implementation: password auth (from env / prompt / file — never logged), per-host connect timeout, error isolation (one host failing doesn't kill the run), concurrent fan-out via `asyncio.gather`.
- Credentials sourced but **not owned** (ADR 0002 non-goal) — read from `VMCTL_SSH_PASSWORD`-style env / prompt / a referenced file.

### C. Remote discovery (ADR 0003)
- Expand each rule's `path` glob **per host** at run time (remote `find`, honoring `exclude`).
- **Report what matched** per host (the "never silently match nothing" rule) — e.g. `ig2: ig-route → [route-00-proxy.log, route-login.log]`.

### D. Prove it
- `vmctl discover <profile>` debug subcommand: connect to every host, run discovery, print the matched files per host per rule.

## Exit criteria

- [ ] A real profile YAML parses into validated models; malformed config fails with a clear message.
- [ ] `vmctl discover test_ig` connects to `ig1` + `ig2` **by password** and lists the files each rule matches on each host.
- [ ] One host being unreachable degrades gracefully (reported, others continue).
- [ ] Config parsing has unit tests; discovery has a `@pytest.mark.integration` test against the live VMs.
- [ ] `asyncssh` + `pyyaml` added to `pyproject.toml`; `uv sync` + the check loop stay green.

## Non-goals (this milestone)
- Any codec/framing or ECS enveloping (→ M03).
- `tail` or `search` behaviour (→ M04/M05).
- The offset registry (→ M07).

## Progress

- 2026-07-22: Milestone opened from the roadmap; foundation for M03/M04.
