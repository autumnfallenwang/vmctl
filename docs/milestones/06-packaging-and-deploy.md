---
milestone: 6
title: Packaging & deploy hardening
status: planned
started: TBD
---

# M06 — Packaging & deploy hardening

Make vmctl shippable: a wheel that installs into a plain venv via `pip` on a
RHEL-like box (no uv at runtime), with credential handling and UX polish, then tag
**0.1.0**. Implements the no-uv deploy constraint of
[ADR 0001](../adr/0001-initial-stack.md). See [ROADMAP.md](ROADMAP.md).

## Scope

### A. Packaging
- Finalize runtime deps (`asyncssh`, `pyyaml`) in `pyproject.toml`; build the wheel.
- Verify `pip install` into a plain stdlib `venv` on a RHEL-like host (e.g. one of the Rocky VMs or a fresh Rocky guest) — `vmctl --version` and a real run, no uv present.

### B. pip-only support
- `uv export --no-hashes -o requirements.txt` for pip-only environments; document the install path.

### C. Robustness + UX
- Credential input (env / prompt / referenced file); never logged or echoed.
- Clear errors for connection failure, auth failure, bad config, empty discovery.
- `--help` for `tail` / `search` / `discover`; a usage section in the README.

### D. Release
- End-to-end smoke on the two-host lab (`tail` + `search`); tag **0.1.0**.

## Exit criteria

- [ ] The built wheel `pip`-installs into a plain venv on a RHEL-like host and runs `vmctl tail` / `vmctl search` end-to-end.
- [ ] `requirements.txt` exported; pip-only install path documented.
- [ ] Credentials are sourced safely and never appear in output/logs.
- [ ] `--help` and README usage are complete and accurate.
- [ ] `0.1.0` tagged; check loop green.

## Non-goals (this milestone)
- New features beyond hardening the existing `tail` / `search`.
- Offset registry (→ M07).

## Progress

- (not started)
