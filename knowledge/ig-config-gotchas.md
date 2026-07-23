---
name: ig-config-gotchas
description: Sharp edges hit while configuring PingGateway IG 2024.11 + the Vagrant/Rocky test env.
metadata:
  type: feedback
---

Pitfalls hit standing up the IG test env ([[ig-test-environment]]) — check these before re-deriving them:

- **`config.json` with `"handler": "_router"` fails** — IG 2024.11 errors `Object _router ... not found in heap` (it isn't pre-registered at parse time). Fix: **omit `config.json`** entirely (IG's default router serves `config/routes/`) and attach audit **per-route** via `"auditService": "<name>"` with the `AuditService` in the route's heap.
- **Per-route log filename uses the route *id*, not its *name*.** Route `00-proxy.json` (name `proxy`) logs to `route-00-proxy.log`. The id is the filename stem.
- **`route-<id>.log` stays empty unless the route emits route-context logs.** IG's logback SiftingAppender already splits per route, but a plain reverse proxy logs nothing there — add **`"capture": "all"`** to the route to populate it with request/response.
- **The audit JSON has no rotation by default** — it grows unbounded. Set `fileRotation` + `fileRetention` on the `JsonAuditEventHandler`. Rotation for `route-*.log` is separate, handled by `logback.xml`.
- **IG's access audit logs only a standard header subset** — custom request headers (e.g. `X-Correlation-Id`) are dropped. For cross-host correlation use IG's `transactionId` or send `X-ForgeRock-TransactionId`.
- **Rocky 9 firewalld blocks IG's `:9080`** from the host by default — open it: `firewall-cmd --add-port=9080/tcp --permanent && firewall-cmd --reload`.
- **Vagrant `file` provisioner nests re-uploads** — uploading dir `ig` to an existing `/tmp/vmctl-ig` creates `/tmp/vmctl-ig/ig`, so a re-provision reads a stale bundle. Clean the target first (`rm -rf`, `run: "always"`) before the file provisioner.
