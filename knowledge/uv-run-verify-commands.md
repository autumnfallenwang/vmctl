---
name: uv-run-verify-commands
description: Run verify tools (ruff/pyright/pytest) via `uv run` — they live in .venv, not on global PATH.
metadata:
  type: feedback
---

vmctl is a uv-managed project: `ruff`, `pyright`, and `pytest` are declared in the `dev` dependency group and installed into `.venv`, not globally. Always invoke them as `uv run ruff check .`, `uv run pyright`, `uv run pytest` (add `-m 'not integration'` for the fast loop).

**Why:** bare `ruff`/`pyright` are not on PATH, and a bare `pytest` resolves to a different interpreter that can't import the `src/`-layout package — so the check loop silently breaks. The devkit verify skills originally shipped bare commands.

**How to apply:** the three `.claude/skills/devkit-{lint,test,typecheck}/SKILL.md` command blocks already use `uv run`. Keep any new verification steps, hooks, or scripts on `uv run` too. See [[project-profile]].
