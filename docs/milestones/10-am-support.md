---
milestone: 10
title: AM support (validate general-purpose via ForgeRock AM)
status: in_progress
started: 2026-07-23
---

# M10 — AM support (validate general-purpose via ForgeRock AM)

Prove vmctl is a **general-purpose** log tool, not an IG-specific one, by pointing it at a
second ForgeRock product — **AM (Access Management) 8.1.1** — and collecting its logs with
**a profile change and no source change**. Extends the test lab of
[ADR 0002](../adr/0002-dev-test-infra.md); the design rationale is
[ADR 0009](../adr/0009-am-to-the-test-lab.md).

## Why this is expected to work (evidence, not hope)

- AM's `access.audit.json` is the **same ForgeRock Common Audit JSON** as IG's — same
  `timestamp` field, same ISO format, one object per line, `http.request.headers` as arrays.
  vmctl's `json` codec + `@timestamp` parsing + ECS envelope already handle exactly this shape
  (confirmed against a live AM audit line, 2026-07-23).
- A full source audit found **one** IG-specific behaviour in code: `_mirror_route_id`
  (`ig.routeId → labels.route_id` in `event.py`). AM logs have no `ig` object, so it simply
  doesn't fire — AM events still collect, minus that one convenience label. Everything else
  (codecs, DSL, planner, pushdown, query, fields, config) is log-agnostic.

## Scope

### A. Infra: make room + install AM on the existing IG VMs
- Bump the two Rocky 9 VMs from **2 GB → 6 GB** RAM (host has 62 GB / 19 GB free); IG only uses
  `-Xmx768m`, so 6 GB comfortably holds IG + AM (`-Xmx2g`) + DS + OS.
- Install **DS 8.1.1 → Tomcat 10.1.57 → AM 8.1.1** under `$HOME` (no sudo needed — the reused
  ping-lab recipe installs to `~`), reusing the installers already downloaded in the
  ping-agent-lab folder. **JDK 25** for AM/DS (DS 8.1.1 is Java-25-compiled), kept separate from
  the system **JDK 17** that IG needs — per-service `JAVA_HOME`.
- Drive a little auth traffic so AM writes real `access.audit.json`.

### B. AM profile — the actual test of the hypothesis
- A `test_am` profile: same two hosts, `base_dir` = AM's audit dir, a `json` input for
  `*.audit.json*` (access/authentication/activity/config), and a `multiline` input for the text
  debug logs. **No code change.** If this produces correct ECS, the general-purpose claim holds.

### C. Validate
- `discover` / `fields` / `tail` / `search` against AM on both hosts; confirm AM events come out
  as ECS NDJSON, queryable by Query DSL, merged across hosts.

## Exit criteria

- [x] Both VMs run AM + DS (started), writing `access.audit.json`, without breaking the IG lab.
- [x] A `test_am` profile collects AM audit logs with **zero source change** — the hypothesis, proven.
- [x] `vmctl fields test_am` reports AM's fields (3 datasets, 50 fields); `search` returns AM events from both hosts (91 from ig1, 76 from ig2, merged + time-sorted).
- [x] The IG lab still works — `vmctl discover test_ig` green on both hosts post-upgrade; IG re-enabled for boot.
- [ ] A marked integration test drives AM traffic and asserts AM events collect; check loop green. *(manual validation done; automated test still to add)*

## Non-goals (this milestone)
- Any vmctl source change to "support AM" — the whole point is that none is needed. If one turns
  out to be required, that is itself the finding, recorded here.
- Full AM feature setup (policies, federation) — only enough AM to emit audit logs.
- Generalizing `_mirror_route_id` into a config-driven field mirror — noted as a possible tidy-up,
  not required (it's inert for AM, not broken).

## Banked recipe (from the ping-agent-lab, hard-won — reuse, don't rediscover)

- Stack: **JDK 25 (Temurin)** · **Tomcat 10.1.57** (Jakarta — AM 8.1 will not run on Tomcat 9) ·
  AM 8.1.1 · **external DS 8.1.1**. Installers in `<ping-agent-lab>/AM/` (war, zip, Amster, DS).
- Order: **DS first** (AM won't boot without its config store), then Tomcat + AM.
- DS 8.x rejects clear-LDAP binds ("Confidentiality Required") → relax `require-secure-authentication`.
- `install-openam --cfgStore dirServer`. Install everything under `$HOME` (no passwordless sudo).

## Risks

- **Reboot to apply the RAM bump kills IG** — `pinggateway.service` is not enabled for boot.
  Mitigation: captured IG's start path; restore with `sudo systemctl start pinggateway stub-app`
  via `vagrant ssh` after the reload. (Enabling it for boot is a nice side-fix.)
- **JDK conflict**: DS wants 25, IG wants 17. Keep JDK 25 out of the system default; point only
  DS/AM at it. If IG breaks, that is a regression to fix, not accept.
- **Different OS from the recipe**: ping-lab built on Ubuntu 22.04; ours is Rocky 9.3. The Java
  stack is portable, but OS-level steps (unzip, paths, firewall ports) differ.

## Progress

- 2026-07-23: Milestone opened. Confirmed AM audit == IG's Common Audit JSON (live sample);
  source audit found the lone IG-ism (`_mirror_route_id`, inert for AM). VM state probed: Rocky
  9.3, 2 GB, system JDK 17, 68 GB free, no passwordless sudo; IG = `pinggateway.service` (not
  boot-enabled). Installers located in the ping-lab folder.
- 2026-07-23: **Infra upgrade done + verified.** Both VMs bumped 2 GB → 6 GB (via `virsh
  setmaxmem/setmem --config` on the persistent domain — vagrant-libvirt won't apply memory on
  reload; Vagrantfile synced). IG restored on both and **enabled for boot** (fixing the gap where
  a reboot silently killed it). IG lab proven healthy: ig1 serves HTTP 200, vmctl discovers all
  logs on both hosts.
- 2026-07-23: **DS 8.1.1 up on ig1**, AM-ready. Staged JDK 25 + Tomcat 10.1.57 (downloaded on the
  VM) + the ForgeRock installers (SFTP from the lab folder). DS installed under `~/am-stack/opendj`
  with the `am-config` / `am-identity-store` / `am-cts` profiles, listening on :1389/:4444;
  `require-secure-authentication` relaxed so AM can bind over clear LDAP (a clear-LDAP bind now
  succeeds). Two iterations to get here: DS tools need `DS_JAVA_HOME` (not `JAVA_HOME`) to find
  JDK 25, and the deprecation warning had leaked into the captured deployment ID. State + creds in
  gitignored `testenv/infra/am-lab.env`. **Next: Tomcat + deploy am.war + `install-openam` → drive
  traffic → build the `test_am` profile.**
- 2026-07-23: **AM fully up on both hosts; hypothesis PROVEN.** ig1: Tomcat 10.1.57 + `am.war`
  deployed (`am1.vmctl.local` in /etc/hosts via `vagrant ssh` sudo — the `vmctl` user's sudo needs
  a password), AM configured with `install-openam --cfgStore dirServer` against the external DS,
  auth traffic driven → `~vmctl/openam/var/audit/*.audit.json` populated. Same Common Audit JSON
  shape as IG. ig2 provisioned the same way. **Validated with zero source change:**
  `discover`/`fields`/`search` over `test_am` — events from both hosts merged. `test_am` profile
  added to `vmctl.example.yml` + `vmctl.yml`. `userStoreType=LDAPv3ForOpenDS`, Amster is a Groovy
  shell (`:h`). *(This first pass built two **independent** instances — corrected next.)*
- 2026-07-23: **Rebuilt to a production-faithful topology** (per verified PingDS 8.1 + PingAM 8.1
  docs; the first pass was two isolated deployments). Corrected a wrong assumption up front: **DS 8
  has no `dsrepl enable`** — replication is a *setup-time* config (`--replicationPort 8989`
  + `--bootstrapReplicationServer` ×2 + a **shared deployment ID**), and replicas from identical
  profile data sync automatically (no `dsrepl initialize`). **DS: fully replicated pair** —
  `ds1`/`ds2.vmctl.local`, one shared deployment ID; `dsrepl status` GOOD on every base DN
  (`ou=am-config`/`ou=identities`/`ou=tokens`/schema), 0 ms delay, matching entry counts. **AM: one
  site `vmctlsite`** — `am1` installed as primary with `--lbSiteName`/`--lbPrimaryUrl`, `am2` added
  as a second server (same site + a **shared `--pwdEncKey`**, sidestepping the encryption-key
  copy), each pointing at its local replicated DS. Proof the config is genuinely shared: querying
  **ds1** shows **am2's** server registration (it wrote to ds2, replicated across). /etc/hosts +
  firewall (1389/4444/8989/1636) set on both via `vagrant ssh`; `@reboot` crontab starts DS→Tomcat
  so the stack survives reboots. vmctl over the site still collects from both hosts, zero code
  change. Topology + shared IDs recorded in gitignored `am-lab.env`. **Infra + validation exit
  criteria met**; only the automated integration test remains.
- 2026-07-23: **Full log-surface coverage.** Mapped every log the AM site + replicated DS emit
  and built a docs-verified trigger catalogue + script (`testenv/engine/am-drive.sh`,
  `AM-LOGS.md`): AM audit ×4 (access/activity/authentication/config), DS `ldap-access` (both
  Common Audit JSON), AM debug (16 logback files, enabled live via `/am/Logback.jsp`),
  `catalina.out`, DS `errors`. Drove all of them on both hosts and extended `test_am` to collect
  the lot (base_dir `/home/vmctl`; json for audit, multiline for the text logs). **vmctl parses
  every family with zero source change** — `fields` reports 5 datasets / 85 fields across both
  hosts; per-family search: am-audit 765, ds-audit 20580, am-container 261, ds-errors 80, am-debug
  events, incl. `AM-CONFIG-CHANGE` (distinct `operation`/`objectId` schema) and DS `DJ-LDAP`.
  Fixed a real site bug found by triggering: an **added AM server 500s on authentication until its
  keystores/secret stores are synced** from the primary — copied `openam/security/{keystores,
  secrets}` am1→am2 + restart, then am2 auth returns 200 (docs flag this as a manual step the
  passive install skips). AM 8 debug is **logback** (`/am/Logback.jsp`), not `Debug.jsp`.
