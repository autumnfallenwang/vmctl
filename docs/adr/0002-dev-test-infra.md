# 0002 — Dev/test infrastructure

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder

## Context

vmctl streams and searches logs across the hosts of one deployment over SSH. To develop and test it we need a realistic environment that produces **real ForgeRock IG logs across more than one host** — that is the exact condition the tool exists to handle, and no such multi-host environment exists yet.

We surveyed two on-hand local labs:

- **`PAIC/SSO_SLO_TEST/POC_070726/test-infra`** — a single Ubuntu 22.04 VM (`sso-poc`, `192.168.122.63`) running the full SSO chain: Tomcat 9 + AM 7.5.2, embedded DS, **PingGateway IG 2024.11.1** on `:9080`, a stub app on `:8081`. It carries our target IG version, a working IG instance layout (`/home/ubuntu/ig-instance/config/{admin.json,routes/sso.json}`), a `pinggateway.service` systemd unit, and a documented **no-sudo libvirt/cloud-init build recipe** (`vol-create-as` + `vol-upload`).
- **`learnAndCert/AI Learning/ping-agent-lab`** — a single Ubuntu 22.04 VM (`am-gym`, `192.168.122.252`) running AM 8.1.1 + external DS 8.1.1, **no IG**. About token-exchange/delegation, not IG logs. Same SSH key.

Neither matches what we need. Both are single-VM (vmctl's whole point is multi-host fanout) and both are Ubuntu, whereas vmctl's stated runtime constraint is **stock RHEL, base tools only** — testing on Ubuntu would not exercise that faithfully.

Two forces shape the design. First, **vmctl connects to each host directly over SSH and never through the load balancer**; in production the LB only *spreads traffic*, so the test environment does not need an LB — it needs each host to accumulate its own, *differing* logs. Second, the product code (`src/vmctl/`) does not exist yet, but infrastructure and test-engine code is about to, so we need a code layout that keeps non-product code out of the shipped wheel from day one.

## Decision

Build a purpose-made two-host test environment and lay the empty project framework around a strict packaging boundary. Specifically:

1. **Two Rocky 9 (RHEL-compatible) VMs, one PingGateway IG 2024.11.1 each, no AM/DS.** Rocky 9 to match the production RHEL/base-tools constraint. Two hosts is the minimum that exercises fanout, cross-host merge-ordering, per-host labelling, and dedup; scaling to 4 later is just adding YAML entries.
2. **Each IG runs a minimal `ReverseProxyHandler` route to a per-host stub upstream, with JSON logging enabled** — real ForgeRock-format logs without an AM dependency.
3. **No load balancer. A test engine stands in for the LB's only relevant function** (spreading traffic). Two modes: **live** (drive real IG requests) and **replay** (append a captured golden corpus with fresh timestamps/transaction-ids and per-host variation). **Replay is the default** (deterministic, scriptable); live is opt-in for end-to-end realism and corpus capture. The engine is what lets us manufacture the scenarios vmctl must survive: a transaction-id landing on both hosts, an event only one host sees, clock skew, bursts, and the occasional broken/partial JSON line.
4. **Test hosts permit password SSH** so vmctl's actual auth path (username/password) is exercised, even though provisioning itself uses a key.
5. **Single repo, `src`-layout.** The product lives in `src/vmctl/` — the sole packaged unit. `tests/` (the pytest suite) and `testenv/{infra,engine,corpus}/` (the test world) sit outside `src/` and are excluded from the wheel by the packaging boundary, not by a repo split. One clone gets the tool, the environment, and the tests.
6. **Provisioning reuses the POC's proven recipe:** libvirt/qemu (`qemu:///system`) + cloud-init, no-sudo `vol-create-as`/`vol-upload`, NAT on `192.168.122.0/24`, JDK 17 for IG, and the on-hand `PingGateway-2024.11.1.zip` binary.

## Consequences

**Positive**

- Faithful to vmctl's RHEL / base-tools constraint — whatever passes in this environment is trustworthy for production.
- Two hosts give genuine fanout, and the per-host log divergence is real rather than simulated.
- The test engine yields **deterministic, scriptable** log corpora that stress vmctl's merge/search/dedup precisely — better control than a real LB could give.
- `src`-layout plus the packaging boundary keeps the wheel clean automatically; tests import the *installed* package, which is exactly how we prove the "installs into a plain venv via pip" constraint.
- Reuses a proven libvirt recipe and an IG 2024.11.1 binary we already have — no downloads, no new provisioning research.

**Negative / trade-offs**

- Building a Rocky 9 base is new work (the existing base image is Ubuntu jammy) — a one-time cost.
- A two-mode engine (live + replay) is more to build than a single driver; mitigated by making replay primary and keeping live minimal.
- No AM means IG logs are proxy/route logs, not full auth-flow logs — acceptable for log-plumbing work; a later round can add AM if auth-shaped logs are needed.
- Password SSH on the test hosts is a deliberate fidelity choice; fine inside an isolated NAT lab, but must never become a pattern for real deployments.

**Risks**

- IG's real JSON log format and on-disk paths on 2024.11 must be **confirmed against the live env** before the replay engine can be faithful — parked as the next milestone's investigation.
- Rocky 9 + IG 2024.11 has not been run in-house (the POC ran IG on Ubuntu). Low risk — IG 2024.11 supports JDK 17 and RHEL 9 is a supported platform — but it is unverified until M01.

## Notes

- Builds on [0001](./0001-initial-stack.md) (initial stack). The test engine and all of `testenv/` are **dev-only and never shipped** in the wheel.
- Source labs referenced: `PAIC/SSO_SLO_TEST/POC_070726/test-infra` and `learnAndCert/AI Learning/ping-agent-lab`.
- Execution plan and exit criteria live in [`docs/milestones/01-test-infra-and-framework.md`](../milestones/01-test-infra-and-framework.md).
