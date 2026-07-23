---
name: devkit-lint
description: Use when the user says "lint", "format", "fix the lint", "check formatting", or when `devkit-task`'s check loop invokes this skill.
allowed-tools: Bash
---

Run the lint command for vmctl. If `$ARGUMENTS` contains the word `fix`, run the auto-fix variant; otherwise run the check-only variant.

## Commands

- **python (ruff)**
  - check: `uv run ruff check .`
  - fix: `uv run ruff check --fix .`

## Reporting

After running:

- **Exit 0** → report "Lint passed." and stop.
- **Non-zero exit** → show the first 20 lines of output. If not already in fix mode, ask the user whether to re-invoke with `fix`. Do not re-run automatically.

## Notes

- This skill is invoked by `devkit-task`'s check loop as part of the standard verification sequence. It is also user-facing via natural language ("lint", "fix the lint", etc.).
- If multiple language sections are listed above, run each in order. A non-zero exit from any section stops the sequence.
