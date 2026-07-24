# 0009 — Add ForgeRock AM to the test lab, to validate general-purpose

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project founder

## Context

vmctl was built and tested against ForgeRock **IG** only ([ADR 0002](./0002-dev-test-infra.md)),
yet it was designed to be **general-purpose** — a Logstash-model log collector ([ADR 0003](./0003-log-source-config-model.md))
with an ECS envelope ([ADR 0004](./0004-ecs-output-schema.md)), nothing IG-specific by intent.
The claim "supporting another product is just a profile change, no code change" has never been
*demonstrated*. This ADR fixes how we demonstrate it: add a second ForgeRock product — **AM
(Access Management) 8.1.1** — to the lab and collect its logs.

Two facts make AM the right, cheap test:

- AM emits the **same ForgeRock Common Audit JSON** as IG (verified against a live AM
  `access.audit.json`): same `timestamp` field and ISO format, one object per line,
  array-valued headers — exactly what vmctl's `json` codec already frames.
- A full source audit found **one** IG-specific line of behaviour (`_mirror_route_id`), and it is
  *inert* for AM (no `ig` object), not broken. So the hypothesis is well-founded before we start.

## Decision

**Add AM to the existing two-VM lab rather than standing up new hosts, and validate AM support as
a profile-only change.**

- **Reuse the two Rocky 9 IG VMs**, bumped **2 GB → 6 GB** RAM (the host has ample headroom). AM
  runs *alongside* IG, not replacing it — two products' logs on the same hosts is a stronger test
  of vmctl's generality, and keeps the IG lab intact.
- **Install under `$HOME`, no sudo**, reusing the AM/DS/Amster installers already present in the
  ping-agent-lab folder (copied out; that project's running VM is never touched). Stack and order
  follow that lab's proven recipe: **JDK 25 → DS 8.1.1 → Tomcat 10.1.57 → AM 8.1.1**, DS first.
- **Two JDKs coexist**: DS 8.1.1 is Java-25-compiled and forces JDK 25; IG 2024.11 runs on the
  system JDK 17. JDK 25 is installed to `$HOME` and used only by DS/AM via per-service
  `JAVA_HOME`; the system default stays 17 so IG is untouched.
- **No vmctl source change is permitted as "AM support."** If AM logs collect with only a new
  profile, the general-purpose claim is proven. If a source change turns out to be *required*,
  that is a finding — recorded, and a sign the tool was less general than believed.

Alternatives considered: (a) reuse the ping-agent-lab's `am-gym` VM directly — rejected: it is
another project's playground, and it is key-auth-only while vmctl is password-only. (b) Stand up
fresh AM-only VMs — rejected as heavier for no extra signal; the IG VMs already have the password
SSH path vmctl needs. (c) Replace IG with AM on the VMs — rejected: coexistence tests more.

## Consequences

- **Positive:** the "just change the profile" claim becomes a demonstrated fact, not an assertion,
  against a genuinely different product. The lab gains a second log shape (AM audit + AM debug
  text) for free. Reusing the ping-lab recipe skips the multi-day install trial-and-error they
  already paid for. The password-SSH path (ADR 0002) is reused as-is.
- **Costs / risks:** installing DS + AM is heavy and iterative, on a different OS (Rocky) than the
  recipe was proven on (Ubuntu). The RAM bump needs a reboot, which drops IG (`pinggateway.service`
  is not boot-enabled) — restored manually, and enabling it for boot is a cheap side-fix. Two JDKs
  on one host is a small ongoing complexity.
- **Boundary:** this ADR is about the **test lab**, like ADR 0002 — not about vmctl's code, which
  by design does not change. Executed in [milestone 10](../milestones/10-am-support.md).

## Notes

- The one latent IG-ism, `_mirror_route_id`, could later be generalized into a config-driven
  "mirror JSON field X → labels.Y" filter, making the tool cleanly product-neutral. Deferred —
  it is inert for AM, so it does not block this milestone.
- Builds on [0002](./0002-dev-test-infra.md) (the lab), [0003](./0003-log-source-config-model.md)
  (the general Logstash model this validates), and [0004](./0004-ecs-output-schema.md) (ECS).
