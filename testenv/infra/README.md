# testenv/infra

VM provisioning for the vmctl test environment. Dev-only — never shipped in the
wheel. Decisions: [ADR 0002](../../docs/adr/0002-dev-test-infra.md).

Two identical **Rocky 9** hosts (`ig1`, `ig2`), each destined to run one
PingGateway IG. Provisioned with **Vagrant + libvirt** using the local
`generic/rocky9` box. vmctl reaches each host **directly over SSH** — there is no
load balancer.

## Layout

- `Vagrantfile` — defines `ig1` / `ig2` (2 vCPU, 2 GB, static IPs on a private net).
- `provision/enable-password-ssh.sh` — creates the `vmctl` login + enables password SSH.
- `provision/install-ig.sh` — installs JDK 17 + PingGateway IG, lays down config, runs it under systemd, opens firewalld 9080.
- `ig/` — the IG instance config (committed): `config/admin.json`, `config/routes/00-proxy.json` (no-AM reverse proxy with JSON audit), `stub-app.py`, `systemd/*.service`.
- `inventory.yml` — host record (name, IP, users); grows into vmctl's profile format.
- `ssh_config` — convenience key-based access (`ssh -F ssh_config ig1`).
- `creds.env.example` — template; copy to `creds.env` (gitignored) with a real password.
- `artifacts/` — **gitignored**; drop the licensed `PingGateway-2024.11.1.zip` here before bringing up.

## Prerequisite: the IG binary

The PingGateway binary is licensed and **not committed**. Put it in `artifacts/`:

```sh
mkdir -p artifacts
cp /path/to/PingGateway-2024.11.1.zip artifacts/
```

## Bring up

```sh
cp creds.env.example creds.env      # then edit creds.env, set VMCTL_SSH_PASSWORD
set -a; source creds.env; set +a    # export creds for the provisioner
vagrant up                          # boots ig1 + ig2 (box is local — no download)
vagrant status
```

## The IG on each host

PingGateway IG **2024.11.1** on `:9080`, no AM — one `ReverseProxyHandler` route
(`00-proxy`) to the local stub (`:8081`). Drive traffic with
`curl http://192.168.77.11:9080/anything` → proxied to the stub and logged.

### Logs it produces (under `/opt/ig-instance/logs/`)

| File | Level | Format | Configured in |
|---|---|---|---|
| `route-system.log` | system (startup, route load, errors) | pipe-delimited text | `config/logback.xml` (global) |
| `route-<routeId>.log` (e.g. `route-00-proxy.log`) | per-route request/response capture | pipe-delimited text | `config/logback.xml` SiftingAppender + the route's `"capture"` |
| `audit/access.audit.json` | per-request access audit | one JSON object per line | the route's `AuditService` / `JsonAuditEventHandler` |

The **audit JSON** is the clean, structured ForgeRock log vmctl primarily targets
(`transactionId`, `http.request`, `response`, `ig.routeName`). The two `route-*.log`
files are semi-structured text — a second shape vmctl must handle.

**Rotation:** `route-*.log` rotate via logback (10 MB/file, 7 days, 200 MB cap);
the audit JSON rotates via its handler (`fileRotation`/`fileRetention`, 10 MB, 7 files).

Clean snapshot per host: `vagrant snapshot restore ig1 ig-baseline`.

## Access

| Path | How | Who |
|---|---|---|
| Key auth | `vagrant ssh ig1` / `ssh -F ssh_config ig1` | humans |
| Password auth | as user `vmctl` (see `creds.env`) | **vmctl's real path** |

Hosts: `ig1` = `192.168.77.11`, `ig2` = `192.168.77.12`.

## Tear down

```sh
vagrant destroy -f      # removes both VMs
```
