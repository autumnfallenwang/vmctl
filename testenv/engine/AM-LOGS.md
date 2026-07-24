# AM + DS log map & trigger catalog

What every log the AM site / replicated DS writes, where it lives, how to trigger it, and
how vmctl collects it. Docs-verified against PingAM / PingDS 8.1. Generate the events with
[`am-drive.sh`](am-drive.sh); collect them with the `test_am` profile (see
`testenv/infra/vmctl.example.yml`). Paths are under `~vmctl` on each host.

## The log surface

| Log | Path (rel. to `/home/vmctl`) | Format | vmctl input | Triggered by |
|---|---|---|---|---|
| **AM audit — access** | `openam/var/audit/access.audit.json` | Common Audit JSON, 1/line | `am-audit` (json) | every REST call (`AM-ACCESS_ATTEMPT` / `AM-ACCESS-OUTCOME`) |
| **AM audit — authentication** | `openam/var/audit/authentication.audit.json` | JSON | `am-audit` | authenticate success/fail (`AM-TREE-LOGIN-STARTED/COMPLETED`, `AM-NODE-LOGIN-COMPLETED`, `AM-LOGOUT`) |
| **AM audit — activity** | `openam/var/audit/activity.audit.json` | JSON | `am-audit` | session create/logout (`AM-SESSION-CREATED/LOGGED_OUT/DESTROYED`), connection factories |
| **AM audit — config** | `openam/var/audit/config.audit.json` | JSON (distinct keys: `operation`, `changedFields`, `objectId`) | `am-audit` | any config change (`AM-CONFIG-CHANGE`, `AM-BOOT-JSON-UPDATED`) — e.g. create a realm |
| **DS audit — LDAP access** | `am-stack/opendj/logs/ldap-access.audit.json` | Common Audit JSON (`eventName: DJ-LDAP`) | `ds-audit` (json) | every LDAP op AM makes — automatic, high volume |
| **AM debug** | `openam/var/debug/{Authentication,Session,OAuth2Provider,Policy,CoreSystem,IdRepo,…}` (16 files) | logback text, lines lead `HH:MM:SS.mmm` | `am-debug` (multiline) | **off by default** — raise the level at `/am/Logback.jsp` (see below) |
| **AM/Tomcat container** | `am-stack/tomcat/logs/catalina.out` | logback text (same as debug) | `am-container` (multiline) | AM runtime — automatic |
| **DS diagnostic** | `am-stack/opendj/logs/errors` | text, lines lead `[dd/Mon/yyyy:HH:MM:SS +zzzz]` | `ds-errors` (multiline) | server events at/above severity — automatic |
| DS `server.out`, `replication`, `stats/*` | — | text / mixed | (not in the profile) | lifecycle / replication |

Both AM and DS Common Audit are **one JSON object per line** with a top-level ISO-8601
`timestamp` (dot-millis, `Z`) — exactly the shape vmctl's `json` codec + `@timestamp`
parsing already handle, which is why AM/DS audit collection needs no source change.

## Triggering (docs-verified, PingAM/PingDS 8.1)

`am-drive.sh <am-fqdn> <amadmin-pw>` runs the full set on one host:

- **authenticate** (success/fail): `POST /am/json/realms/root/authenticate` with
  `X-OpenAM-Username/Password` + `Accept-API-Version: resource=2.0, protocol=1.0`.
- **session validate / logout**: `POST /am/json/realms/root/sessions?_action=validate` /
  `?_action=logout` with the `iPlanetDirectoryPro` token.
- **config change**: `POST /am/json/global-config/realms` (no `_action`) creates a realm →
  `AM-CONFIG-CHANGE`.
- **policy evaluate**: `POST /am/json/realms/root/policies?_action=evaluate`.
- **debug**: AM 8 uses **logback**, not `Debug.jsp`. Live-enable at `/am/Logback.jsp`
  (amAdmin only) — POST `logger`, `loggerLevel` (`Off`/`Error`/`Warning`/`Information`/
  `Debug`/`Trace`), `formToken` (CSRF). Non-persistent; revert to `Error` when done.

## Sharp edges found while building this

- **eventName delimiters are inconsistent** — `AM-ACCESS_ATTEMPT` (underscore) vs
  `AM-ACCESS-OUTCOME` (hyphen). Filter carefully.
- **Added AM site servers need their keystores/secret stores synced** from the first server
  or authentication returns **HTTP 500**. We copy `openam/security/{keystores,secrets}` from
  am1 → am2 and restart (the passive install does not do this).
- **Debug files fill only for enabled loggers** (or when a component is erroring). Healthy AM
  at the default `Error` level leaves them empty — that is expected, not a collection gap.
