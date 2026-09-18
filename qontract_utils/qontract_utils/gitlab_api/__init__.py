"""GitLab group/project administration API client.

This package provides a stateless GitLab client for group/project
administration, following the three-layer architecture pattern (ADR-014).

Layer 1 (Pure Communication):
- GitlabApi: Stateless API client scoped to a single GitLab instance, with
  hooks for metrics and rate limiting

Hook System (ADR-006):
- GitlabApiCallContext: Context passed to hooks
- pre_hooks: Hook system for metrics, logging, latency

Example:
    >>> from qontract_utils.gitlab_api import GitlabApi
    >>> api = GitlabApi(url="https://gitlab.example.com", token="...")
    >>> group = api.get_group("my-group")
    >>> project = api.create_project(group.id, "my-project")
"""

from qontract_utils.gitlab_api.client import GitlabApi, GitlabApiCallContext
from qontract_utils.gitlab_api.models import GitlabGroup, GitlabProject

__all__ = [
    "GitlabApi",
    "GitlabApiCallContext",
    "GitlabGroup",
    "GitlabProject",
]
