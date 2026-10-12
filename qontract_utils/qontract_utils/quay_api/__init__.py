"""Quay API client.

This package provides a stateless Quay API client following the three-layer
architecture pattern (ADR-014).

Layer 1 (Pure Communication):
    - QuayApi: Stateless API client scoped to a single organization, with hooks
      for metrics and rate limiting

Hook System (ADR-006):
    - QuayApiCallContext: Context passed to hooks
    - pre_hooks: Hook system for metrics, logging, latency

Example:
    >>> from qontract_utils.quay_api import QuayApi
    >>> api = QuayApi(org="my-org", token="...", base_url="https://quay.io")
    >>> repos = api.list_images()
    >>> for repo in repos:
    ...     print(repo.name, repo.is_public)
"""

from qontract_utils.quay_api.client import TIMEOUT, QuayApi, QuayApiCallContext
from qontract_utils.quay_api.models import (
    QuayRepo,
    RobotAccount,
    RobotAccountPermission,
    RobotAccountRepository,
)

__all__ = [
    "TIMEOUT",
    "QuayApi",
    "QuayApiCallContext",
    "QuayRepo",
    "RobotAccount",
    "RobotAccountPermission",
    "RobotAccountRepository",
]
