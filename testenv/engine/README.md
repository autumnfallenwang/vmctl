# testenv/engine

The test engine that stands in for a load balancer's only relevant function —
spreading traffic across the identical IG hosts so each accumulates its own JSON
audit log. vmctl reads those logs; this generates them. Dev-only — never shipped
in the wheel. See [ADR 0002](../../docs/adr/0002-dev-test-infra.md).

## `drive.py` — minimal round-robin driver (M01-D)

stdlib only, no deps. Round-robins varied request paths across the two IG hosts,
tagging each request with a unique `X-Correlation-Id`.

```sh
python3 drive.py                 # 30 requests across the two default IG hosts
python3 drive.py --count 100 --delay 0
python3 drive.py --hosts 192.168.77.11:9080 192.168.77.12:9080
```

Then watch the logs diverge, per host:

```sh
cd ../infra
vagrant ssh ig1 -c 'tail -f /opt/ig-instance/logs/audit/access.audit.json'
```

## Later (M02)

The full engine: **replay** of a captured golden corpus and **live** mode, with
deterministic stress scenarios — the same transaction-id landing on both hosts,
host-only events, clock skew, bursts, and broken/partial JSON lines.
