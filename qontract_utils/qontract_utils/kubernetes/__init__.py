"""Kubernetes API client using lightkube.

This package provides a stateless Kubernetes API client following the
three-layer architecture pattern (ADR-014).

Layer 1 (Pure Communication):
- KubernetesApi: Stateless API client with hooks for metrics and logging
- Typed exceptions mapped from lightkube ApiError

Hook System (ADR-006):
- KubernetesApiCallContext: Context passed to hooks
- Built-in hooks for metrics, logging, latency

Example:
    >>> from qontract_utils.kubernetes import KubernetesApi
    >>> api = KubernetesApi(server="https://cluster:6443", token="...")
    >>> ns = api.get_namespace("my-namespace")
    >>> print(ns.metadata.name)
"""

from lightkube.resources.core_v1 import Namespace

from qontract_utils.kubernetes.client import (
    TIMEOUT,
    KubernetesApi,
    KubernetesApiCallContext,
)
from qontract_utils.kubernetes.exceptions import (
    AlreadyExistsError,
    ForbiddenError,
    KubernetesApiError,
    NotFoundError,
    UnauthorizedError,
    from_api_error,
)

__all__ = [
    "TIMEOUT",
    "AlreadyExistsError",
    "ForbiddenError",
    "KubernetesApi",
    "KubernetesApiCallContext",
    "KubernetesApiError",
    "Namespace",
    "NotFoundError",
    "UnauthorizedError",
    "from_api_error",
]
