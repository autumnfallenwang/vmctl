---
name: project-profile
description: Seeded by /devkit-init on 2026-07-22. Captures who this project is and what shape it has.
metadata:
  type: project
---

# vmctl

A CLI for streaming and searching ForgeRock logs across identical SSH-reachable deployments, when you don't have ELK

## What this project is

When a product like ForgeRock IG is deployed identically across several servers behind a load balancer, each host keeps its own system logfile and its own per-route logfiles — so debugging means chasing logs scattered across machines. The clean answer is Filebeat on each host shipping into Elastic, but when that isn't available and SSH is the only connectivity you have, you still want to stream and search with a standard format. vmctl is that fallback: a CLI that fans out over SSH to the hosts in a named deployment profile, targets a particular log path or logfile, and emits JSON labelled with its source. Output is consumed by humans at a terminal, by a local logfile, and by AI agents — the tool is meant to be easy for both. The defining constraint is that remote hosts are locked-down standard RHEL with no ability to install anything, so the remote side is limited to base utilities like `tail`.

## Stack at a glance

- **Primary language:** python
- **Package manager:** uv

- **Lint + format:** ruff
- **Tests:** pytest
- **Type checking:** pyright
- **Packaging:** PEP 621 `pyproject.toml` → wheel; uv is dev-time only, artifact installs via `pip` into a plain `venv`
- **Config:** YAML file defining named deployment profiles (e.g. `TEST_IG`) with per-host hostname/username/password
- **Transport:** SSH, username/password auth; specific client library still undecided
- **Output:** JSON envelope adding source metadata around already-JSON ForgeRock log records
- **No database, no server, no frontend**

## Why future-you should keep this entry up to date

This is `type: project`, meaning it's a live cache of project-level context — not history. As the project evolves (new components, removed deps, shifted scope), update this file. Delete it entirely if the project changes shape so fundamentally that the brainstorm answers no longer apply, and capture a fresh one.
