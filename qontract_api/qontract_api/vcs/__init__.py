"""Shared VCS domain layer (ADR-014 Layer 2).

Houses the provider-aware workspace client and its factories so both the
external VCS endpoints and server-side integrations can reuse them.
"""

from qontract_api.vcs.vcs_factory import create_vcs_workspace_client
from qontract_api.vcs.vcs_workspace_client import VCSWorkspaceClient

__all__ = [
    "VCSWorkspaceClient",
    "create_vcs_workspace_client",
]
