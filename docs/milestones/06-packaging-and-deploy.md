---
milestone: 6
title: Packaging & deploy hardening
status: done
started: 2026-07-23
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
- Credential input (env / prompt); never logged or echoed. *(A "referenced file" source
  was dropped from scope — inline / env / prompt cover the realistic cases, and password
  management is the user's responsibility per ADR 0002.)*
- Clear errors for connection failure, auth failure, bad config, empty discovery.
- `--help` for `tail` / `search` / `discover` / `fields`; a usage section in the README.

### D. Release
- End-to-end smoke on the two-host lab (`tail` + `search`); tag **0.1.0**.

## Exit criteria

- [~] The built wheel `pip`-installs into a plain venv and runs end-to-end — verified on the
      dev host (venv + `pip install` the wheel → `vmctl --version`, deps resolved). **The
      clean-RHEL-box proof (online + offline) was waived by decision** — not independently run.
- [x] `requirements.txt` exported; pip-only + airgapped install path documented (README + in-file).
- [x] Credentials are sourced safely (inline / env / prompt) and never appear in output/logs.
- [x] `--help` and README usage are complete and accurate (Usage + Install + Build + Release).
- [~] Check loop green (164 fast + 7 live). `0.1.0` **not tagged here** — releases are now a
      tag push handled by CI (`.github/workflows/release.yml`); cutting the tag is the trigger.

## Non-goals (this milestone)
- New features beyond hardening the existing `tail` / `search`.
- Offset registry (→ M07).

## Progress

- 2026-07-23: Groundwork done (this session, partly ahead of M06 opening): `--help` for all
  four subcommands + README Usage section (shipped in `fffe41e`); credentials via inline / env
  / prompt, never logged.
- 2026-07-23: Version bumped `0.0.1` → `0.1.0` (dynamic from `vmctl.__version__`); wheel now
  builds as `vmctl-0.1.0-py3-none-any.whl`. Exported `requirements.txt` — the pinned transitive
  tree for pip-only / airgapped installs, with the offline `pip download`/`--no-index` recipe
  documented in-file. **Error-message audit** found and fixed two real defects: the host name
  was printed **twice** on host errors (`TransportError` already carries it, and search / tail /
  fields / discover each re-prepended it), and a connect timeout produced a bare
  `connect failed:` with no reason (tested the exception *object*, always truthy, instead of its
  message). Verified clean across bad-config / unknown-profile / bad-DSL / connect-timeout /
  auth-failure / empty-discovery / empty-search. 164 fast + 7 live still green.
- 2026-07-23: Added a release workflow (`.github/workflows/release.yml`) beyond the original
  scope: a pushed `v*` tag builds the wheel in CI and attaches it to a GitHub Release, gated on
  a tag↔`__version__` match and the check loop. README gained Install / Build / Release sections.
  Corrected two assumed-current action versions against the live registry (`setup-uv` has no
  floating tag → pinned `v9.0.0`; `action-gh-release` → `v3.0.2`). Closing M06 on this basis.

## Outcome

vmctl is shippable: `uv build` produces a `py3-none-any` wheel that `pip`-installs into a plain
venv (Python 3.12 + pip, no uv), pulling `asyncssh`/`pyyaml` and their tree from PyPI — or from a
pre-staged `bundle/` on an airgapped host, per the pinned `requirements.txt`. Version is 0.1.0,
sourced from `__version__`. Releases are automated: push a `v*` tag and CI builds + publishes the
wheel to GitHub Releases, refusing to publish on a tag/version mismatch or a red check loop. The
error-message audit fixed two real, live-only defects (doubled host name; empty `connect failed:`).

Deviations from the plan, all recorded above: the "referenced file" credential source was
**dropped** (inline/env/prompt suffice); the clean-RHEL-box install proof was **waived by
decision** — the wheel is verified installing/running on the dev host but not independently on
Rocky; and the manual `0.1.0` tag step was **replaced** by the release workflow, so the tag is a
deliberate push-button rather than a step taken here. Lesson worth noting: external GitHub Action
versions must be checked against the registry, not assumed — two of three were stale as first
written.

Closed: 2026-07-23
