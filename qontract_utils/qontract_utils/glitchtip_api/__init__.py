"""Glitchtip API client and models.

This package provides a stateless Glitchtip API client following the three-layer
architecture pattern (ADR-014).

Layer 1 (Pure Communication):
- GlitchtipApi: Stateless API client with hooks for metrics and logging
- Models: Pydantic models for organizations, projects, and alerts

Hook System (ADR-006):
- GlitchtipApiCallContext: Context passed to hooks
- pre_hooks: Hook system for metrics, logging, latency

Example:
    >>> from qontract_utils.glitchtip_api import GlitchtipApi
    >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
    >>> orgs = api.organizations()
    >>> for org in orgs:
    ...     print(org.name)
"""

from qontract_utils.glitchtip_api.client import (
    TIMEOUT,
    GlitchtipApi,
    GlitchtipApiCallContext,
)
from qontract_utils.glitchtip_api.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectAlertRecipient,
    RecipientType,
)

__all__ = [
    "TIMEOUT",
    "GlitchtipApi",
    "GlitchtipApiCallContext",
    "Organization",
    "Project",
    "ProjectAlert",
    "ProjectAlertRecipient",
    "RecipientType",
]
