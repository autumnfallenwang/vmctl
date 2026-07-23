---
name: ig-test-environment
description: The 2-host Rocky 9 PingGateway IG lab vmctl is developed against — hosts, log files, and where each log is configured.
metadata:
  type: project
---

The vmctl test environment (`testenv/infra/`, Vagrant + libvirt): two identical **Rocky 9** hosts, **ig1** = `192.168.77.11`, **ig2** = `192.168.77.12`. Each runs **PingGateway IG 2024.11.1** on `:9080` (no AM) reverse-proxying route `00-proxy` to a loopback stub on `:8081`. vmctl reaches each host **directly over SSH** — there is no load balancer.

**The three log shapes IG produces** (under `/opt/ig-instance/logs/`) — vmctl must handle all three:

| File | Level | Format | Configured in |
|---|---|---|---|
| `route-system.log` | system (startup, route load, errors) | pipe-delimited text | `config/logback.xml` (global) |
| `route-<routeId>.log` (e.g. `route-00-proxy.log`) | per-route request/response capture | pipe-delimited text | `config/logback.xml` SiftingAppender + the route's `"capture"` |
| `audit/access.audit.json` | per-request access audit | one JSON object per line | the route's `AuditService` / `JsonAuditEventHandler` |

**Config split:** `logback.xml` is **global** (system + all per-route debug logs + their rotation); the **AuditService** lives **per-route** in the route JSON (access-JSON audit + its rotation). The audit JSON (`transactionId`, `http.request`, `response`, `ig.routeName`) is the clean structured log vmctl primarily targets; the `route-*.log` files are the text shape.

**Operate:** `cd testenv/infra && set -a; source creds.env; set +a && vagrant up|provision|ssh ig1`; drive traffic with `python3 testenv/engine/drive.py`; clean baseline `vagrant snapshot restore ig1 ig-baseline`. The IG binary (`artifacts/`) and `creds.env` are **gitignored**. Access: key auth as `vagrant`, password auth as `vmctl` (vmctl's real path). See [[ig-config-gotchas]] for the sharp edges and [[uv-run-verify-commands]] for the dev loop.
