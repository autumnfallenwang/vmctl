# Architecture

vmctl streams and searches logs across the hosts of a single deployment over SSH, emitting JSON records labelled with the host and file they came from. It exists for the case where logs are scattered across identical servers behind a load balancer and the usual answer — Filebeat shipping into Elastic — isn't available, leaving SSH as the only way in.

## System shape

The tool is a command-line binary meant to be easy for both humans and AI agents to drive. Hosts come from a YAML config and are wrapped into profiles — for example `TEST_IG:` containing `IG1` (hostname, username, password), `IG2`, and so on — with room for whatever other metadata is needed later. A profile names one deployment; the concrete motivating case is a ForgeRock IG deployed identically on 4 servers behind a load balancer, where each host carries its own system logfile plus per-route logfiles. Connections are SSH with username/password. The password may change, and password management is the user's responsibility.

The remote side is a standard RHEL environment with basic commands like `tail` available, but with no ability to install additional tooling — so whatever runs out there must be composed from what is already present. vmctl fans out across the hosts in a profile, targets a particular log path or logfile, and brings the lines back. ForgeRock product logs are already essentially standard JSON, so vmctl does not attempt to parse arbitrary input; it adds metadata on top of each record to label its source. Streaming can go to the terminal and to a local logfile. Search output should also be JSON. The split between filtering on the remote side and filtering locally is not yet settled, and neither is the search query interface.

## Key components

Single Python package. No code exists yet — these are the responsibilities the sketch implies, not modules that have been built or named:

- **CLI entry point** — the human- and agent-facing surface; subcommands for streaming and for searching.
- **Profile config** — loads the YAML file, resolves a profile name (e.g. `TEST_IG`) to its list of hosts and their hostname/username/password plus future metadata.
- **SSH transport** — opens password-authenticated connections to each host in a profile.
- **Remote command layer** — builds the commands run on the far end, restricted to base RHEL utilities.
- **Fan-out / multiplexing** — runs against every host in the profile and merges the returned lines into one stream.
- **Envelope** — wraps each already-JSON ForgeRock record with source metadata (profile, host, logfile/route).
- **Sinks** — terminal output and a local logfile for streaming; JSON for search results.

## Constraints and non-goals

**Constraints**

- **No remote installation.** Remote hosts are stock RHEL and nothing may be installed on them. Only base utilities (`tail`, `grep`, `sed`, `awk`) are available for remote-side work — no agent, no Filebeat, nothing shipped over.
- **Deployable without uv.** uv is a development-time tool only. The project must install into a plain `venv` via `pip`, so packaging stays standard PEP 621 and the runtime has no uv dependency.
- **SSH with username/password only.** That is the connectivity that exists. Passwords may rotate.

**Non-goals**

- **Not a general-purpose log parser.** Scoped to ForgeRock product logs, which are already JSON. vmctl adds a source-labelling envelope rather than parsing arbitrary formats.
- **Not a secret store.** Password management is the user's responsibility — vmctl does not own credential storage or rotation.
- **Not a replacement for ELK.** Filebeat into Elastic remains the right answer when it's available; vmctl is the fallback for when SSH is all you have.
- **Scope is currently narrow.** vmctl is framed as a CLI for managing local VMs, but only the log streaming/search capability is in scope for now.

## Test / development environment

Because vmctl's whole job is multi-host log fanout, it is developed against a purpose-built two-host lab rather than the product code alone. The decisions are recorded in [ADR 0002](adr/0002-dev-test-infra.md); execution lives in [milestone 01](milestones/01-test-infra-and-framework.md).

- **Two Rocky 9 (RHEL-compatible) VMs**, one **PingGateway IG 2024.11.1** each, no AM/DS. Rocky 9 keeps the env faithful to vmctl's stock-RHEL / base-tools constraint; two hosts is the minimum that exercises fanout, cross-host merge, per-host labelling, and dedup (scaling to 4 is just config).
- Each IG runs a minimal `ReverseProxyHandler` route to a per-host stub upstream with **JSON logging enabled** — real ForgeRock-format logs without an AM dependency.
- **No load balancer.** vmctl connects to each host directly over SSH and never through an LB; the LB in production only spreads traffic. A **test engine** stands in for that — a **replay** mode (append a captured golden corpus with fresh timestamps/tx-ids and per-host variation; deterministic, the default) plus an opt-in **live** mode (drive real IG requests). It manufactures the cases vmctl must survive: a tx-id on both hosts, host-only events, clock skew, bursts, broken JSON lines.
- Test hosts permit **password SSH** so vmctl's real username/password auth path is exercised.
- **Repo layout:** single repo, `src`-layout. Product in `src/vmctl/` (the sole packaged unit); `tests/` and `testenv/{infra,engine,corpus}/` sit outside `src/` and are excluded from the wheel by the packaging boundary. The test engine and all of `testenv/` are dev-only and never shipped.

## Open questions

- **SSH transport.** Shell out to the system `ssh` binary (inherits the user's config, jump hosts, known_hosts) or use a library such as `asyncssh` / `paramiko`? Password auth pushes against the plain-binary option; not decided.
- ~~**Where filtering happens.**~~ **Resolved ([ADR 0005](adr/0005-collection-and-search-execution.md)):** both — a sound pushdown on the servers (`find`/`grep`/`awk`) plus exact evaluation on the client, via three-tier predicate resolution.
- ~~**Search query interface.**~~ **Resolved ([ADR 0005](adr/0005-collection-and-search-execution.md)):** KQL, evaluated index-less against the ECS events (no Elasticsearch store).
- **Host-count scale.** Test env is fixed at 2 (see above); production target is ~4 behind an LB. The profile format must not assume a specific count.
- **Python version floor — resolved: 3.12.** Governs the machine vmctl *runs on* (operator/agent/jump host), not the log hosts, which never execute vmctl's Python. RHEL 9 deployment uses the `python3.12` appstream module. To be pinned as `requires-python = ">=3.12"` in [milestone 01](milestones/01-test-infra-and-framework.md).
- **Module breakdown.** The internal layout of `src/vmctl/` is deferred to the first product milestone (M03), once the test harness exists to build against.
