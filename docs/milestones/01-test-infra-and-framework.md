---
milestone: 1
title: Dev/test infrastructure + empty project framework
status: done
started: 2026-07-22
---

# M01 — Dev/test infrastructure + empty project framework

Stand up the two-host Rocky 9 IG test environment and the empty `src`-layout project framework, so every later milestone has both a place to write product code and a realistic multi-host log source to test it against.

**No vmctl product logic ships in this milestone.** This is scaffolding and environment only. Decisions are recorded in [ADR 0002](../adr/0002-dev-test-infra.md).

## Scope

### A. Empty project framework (`src`-layout)

- `pyproject.toml`: PEP 621 metadata, ruff + pyright + pytest config, a `dev`/`test` dependency group for the engine's deps. Console-script entry point `vmctl = vmctl.cli:main`.
- `src/vmctl/__init__.py` (version string) and `src/vmctl/cli.py` with a `main()` that handles `--version`/`--help` via stdlib `argparse` — no product logic, no third-party deps.
- `tests/test_smoke.py` — imports `vmctl`, asserts `--version` runs.
- `testenv/{infra,engine,corpus}/` created with `.gitkeep` + a one-line README each.
- **Python floor: 3.12** (decided 2026-07-22). Pin `requires-python = ">=3.12"`. vmctl runs on the operator's/agent's machine and never on the log hosts, so this governs the deploy target only; RHEL 9 installs use the `python3.12` appstream module, not stock system 3.9.
- **Verify the no-uv deploy path:** build the wheel, `pip install` it into a *plain* `venv` (no uv present), and confirm `vmctl --version` runs.

### B. Rocky 9 base + two VMs

- Build/obtain a Rocky 9 GenericCloud qcow2 base.
- cloud-init seed: login user, provisioning SSH key, **password SSH enabled** (so vmctl's username/password auth path is testable), hostname.
- Provision via libvirt no-sudo (`vol-create-as` + `vol-upload`), NAT `192.168.122.0/24`, adapting the `POC_070726` recipe.
- Two domains: `ig1`, `ig2` (proposed hostnames `ig1.poc.local`, `ig2.poc.local`).
- Record a host inventory (ssh_config and/or a YAML stub that later feeds vmctl's own profile format).

### C. PingGateway IG on each host

- Install JDK 17.
- Unpack `PingGateway-2024.11.1.zip` (on hand at `POC_070726/screenshots/`), set `IG_INSTANCE_DIR`, configure one `ReverseProxyHandler` route → the per-host stub upstream, enable JSON logging, listen on `:9080`.
- A `pinggateway.service` systemd unit per host (adapt the POC unit; drop the AM `isAlive` gate — no AM).
- A trivial stub upstream (`python3 -m http.server` / small `app.py`) per host.
- Snapshot each VM as a clean baseline.

### D. Minimal traffic driver (smoke)

- A small round-robin driver hitting `ig1:9080` and `ig2:9080` **directly** (no LB), enough to watch each host's IG logfiles grow and diverge.
- The full replay engine + stress-scenario corpus is **M02**, not here.

### E. Docs

- ADR 0002 accepted (done).
- `docs/architecture.md`: add the "Test / development environment" subsection (done in this milestone's doc pass).

## Exit criteria

- [x] Empty vmctl framework is pip-installable into a plain venv; `vmctl --version` runs; smoke test + ruff + pyright are green.
- [x] Two Rocky 9 VMs (`ig1`, `ig2`) provisioned and SSH-reachable via **both key and password**; inventory documented.
- [x] PingGateway IG 2024.11.1 running on each host with a JSON-logging route and a stub upstream; clean snapshots taken.
- [x] The traffic driver produces divergent JSON logs on the two hosts, confirmed by tailing both.
- [x] `requires-python = ">=3.12"` pinned in `pyproject.toml`.

## Non-goals (this milestone)

- Any vmctl product logic (config loader, SSH transport, fanout, envelope, sinks).
- The full replay engine, the stress-scenario corpus, or golden-format capture (→ M02).
- AM/DS, a real load balancer, or more than 2 hosts.

## Roadmap (subsequent milestones)

Created as their own files when the prior milestone closes — kept here as a one-line forward plan, not as active milestones:

- **M02 — IG log investigation + test engine.** Capture the real IG 2024.11 JSON log format and on-disk paths from the live env; build the replay engine and the deterministic stress corpus (same tx-id across hosts, host-only events, clock skew, bursts, broken JSON, fixed seed).
- **M03 — vmctl MVP: stream.** YAML profile config + SSH (password) fanout + `tail -F` streaming with the source-labelling envelope, to terminal and local file. Resolves the `src/vmctl` module breakdown.
- **M04 — vmctl: search.** Cross-host search over a log path/file, JSON output, query interface referencing existing search-query tools.
- **M05 — packaging / deploy hardening.** Wheel build, pip/venv install verification on a RHEL-like host, `requirements.txt` export for pip-only environments.

## Progress

- 2026-07-22: Milestone opened; infra decisions recorded in ADR 0002.
- 2026-07-22: Track A shipped — empty `src`-layout framework (`pyproject.toml`, `src/vmctl/{__init__,cli}.py`, smoke tests, `testenv/` tree). Check loop green (ruff/pyright/pytest); pip/venv install of the built wheel runs `vmctl 0.0.1` with no uv. Devkit verify skills switched to `uv run`.
- 2026-07-22: Track B shipped — `ig1`/`ig2` Rocky 9 VMs via Vagrant + libvirt (`testenv/infra/`, static IPs 192.168.77.11/.12). Both reachable by key (vagrant) and password (vmctl user); inventory + ssh_config recorded. Provisioning method amended in ADR 0002 (Vagrant over cloud-init, since the host already had it).
- 2026-07-22: Track C shipped — PingGateway IG 2024.11.1 on both hosts (JDK 17, systemd), one no-AM reverse-proxy route to a local stub, **JSON audit logging** at `logs/audit/access.audit.json` (ForgeRock Common Audit — `transactionId`, `http.request`, `response`, `ig.routeName`). Host→IG→stub verified end-to-end on both; firewalld 9080 opened; clean `ig-baseline` snapshots taken. Config in `testenv/infra/ig/`; IG binary stays gitignored in `artifacts/`.
- 2026-07-22: Track D shipped — `testenv/engine/drive.py`, a stdlib round-robin traffic driver. 40 reqs across both IGs grew each host's audit log 2→22 with divergent paths + per-host transactionId prefixes. **All M01 exit criteria met.** (Finding for M02: IG's default access audit doesn't log arbitrary request headers — use `transactionId`/`X-ForgeRock-TransactionId` for cross-host correlation.)
- 2026-07-22: Logging refined on both hosts — explicit `config/logback.xml` (per-route SiftingAppender → `route-<routeId>.log`, tuned rotation) + `"capture": "all"` on the route (populates `route-00-proxy.log`) + audit `fileRotation`/`fileRetention`. Three log shapes now present: `route-system.log`, `route-<routeId>.log` (both text), `audit/access.audit.json` (JSON). Config split confirmed: logback.xml = global system/route-debug + rotation; AuditService (route) = access JSON + its rotation. Snapshots refreshed.

## Outcome

Shipped the full test scaffold: the pip-installable `src`-layout vmctl framework (no-uv deploy proven) plus a two-host Rocky 9 lab (`ig1`/`ig2`) running PingGateway IG 2024.11.1, each producing real ForgeRock logs in three shapes — `route-system.log`, per-route `route-<id>.log`, and JSON `access.audit.json` — with rotation, driven by a stdlib traffic engine. All five exit criteria met.

Deviations from plan: provisioning switched from cloud-init to **Vagrant + libvirt** (ADR 0002 amended) because the host already had the tooling and the `generic/rocky9` box; the log-format details normally deferred to M02 were partly front-loaded here at the user's request. Lessons captured in [[ig-test-environment]] and [[ig-config-gotchas]].

Closed: 2026-07-22
