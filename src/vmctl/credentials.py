"""SSH password sourcing. A host may carry an inline `password` in the config
(highest priority); this module provides the **fallback** used when a host has none
— from the environment or an interactive prompt. vmctl does not own or store
credentials (docs/adr/0002) and never logs them."""

from __future__ import annotations

import getpass
import os
import sys

DEFAULT_ENV_VAR = "VMCTL_SSH_PASSWORD"


class CredentialsError(Exception):
    """Raised when no password can be sourced."""


def resolve_password(*, env_var: str = DEFAULT_ENV_VAR, allow_prompt: bool = True) -> str:
    """Return the fallback SSH password: from ``env_var`` if set, else an interactive
    prompt. Used only for hosts without an inline ``password`` in the config.

    Raises CredentialsError if neither is available (e.g. non-interactive, no env var).
    """
    value = os.environ.get(env_var)
    if value:
        return value
    if allow_prompt and sys.stdin.isatty():
        return getpass.getpass("vmctl SSH password: ")
    raise CredentialsError(
        f"no SSH password available — set ${env_var} or run in an interactive terminal"
    )
