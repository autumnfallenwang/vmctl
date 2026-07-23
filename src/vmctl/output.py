"""Output sink: NDJSON, one ECS event per line (docs/adr/0004, docs/adr/0007).

The only output format. vmctl is a machine interface — its consumers are agents,
scripts and pipelines — so there is no human-facing rendering to keep in step with the
record, and no flag to choose between them. Pipe it through `jq` if you need eyes on it.

Returns a string without a trailing newline; the caller writes lines to stdout or a file.
"""

from __future__ import annotations

import json
from typing import Any


def to_ndjson(event: dict[str, Any]) -> str:
    """One ECS event as a compact JSON line."""
    return json.dumps(event, separators=(",", ":"), default=str)
