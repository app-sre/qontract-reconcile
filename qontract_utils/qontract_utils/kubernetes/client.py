"""Kubernetes API client using lightkube with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless Kubernetes API client with support for
metrics and logging via hooks (ADR-006).

Uses lightkube for all K8s API communication (binding decision from
docs/design/appsre-13581-kubernetes-client-analysis.md).
"""

import contextvars
import time
from dataclasses import dataclass
from typing import Self

import httpx
import structlog
from lightkube import ApiError, Client
from lightkube.config.kubeconfig import Cluster, KubeConfig, User
from lightkube.generic_resource import create_global_resource
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Namespace
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.kubernetes.exceptions import from_api_error
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409

# OpenShift Project resource (cluster-scoped, like Namespace)
_Project = create_global_resource(
    group="project.openshift.io",
    version="v1",
    kind="Project",
    plural="projects",
)

logger = structlog.get_logger(__name__)

kubernetes_request = Counter(
    "qontract_reconcile_external_api_kubernetes_requests_total",
    "Total number of Kubernetes API requests",
    ["method", "verb"],
)

kubernetes_request_duration = Histogram(
    "qontract_reconcile_external_api_kubernetes_request_duration_seconds",
    "Kubernetes API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)

TIMEOUT = 30


@dataclass(frozen=True)
class KubernetesApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "namespaces.get")
        verb: HTTP verb (e.g., "GET")
        id: Cluster server URL
    """

    method: str
    verb: str
    id: str


def _metrics_hook(context: KubernetesApiCallContext) -> None:
    kubernetes_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: KubernetesApiCallContext) -> None:
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: KubernetesApiCallContext) -> None:
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    kubernetes_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: KubernetesApiCallContext) -> None:
    logger.debug(
        "Kubernetes API request",
        method=context.method,
        verb=context.verb,
        id=context.id,
    )


@with_hooks(
    hooks=Hooks(
        pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
        post_hooks=[_latency_end_hook],
    )
)
class KubernetesApi:
    """Stateless Kubernetes API client using lightkube.

    Layer 1 (Pure Communication) client following ADR-014. Provides methods
    to manage Kubernetes Namespaces via lightkube's typed API.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive KubernetesApiCallContext with method, verb, id
    """

    _hooks: Hooks

    def __init__(
        self,
        server: str,
        token: str,
        *,
        insecure_skip_tls_verify: bool = False,
        timeout: int = TIMEOUT,
        hooks: Hooks | None = None,  # noqa: ARG002
    ) -> None:
        """Initialize Kubernetes API client.

        Args:
            server: Cluster API server URL (e.g., "https://cluster:6443")
            token: Bearer token for authentication
            insecure_skip_tls_verify: Skip TLS certificate verification
            timeout: API request timeout in seconds (default: 30)
            hooks: Optional custom hooks to merge with built-in hooks.
        """
        self._server = server.rstrip("/")
        config = KubeConfig.from_one(
            cluster=Cluster(server=self._server, insecure=insecure_skip_tls_verify),
            user=User(token=token),
        )
        self._client = Client(config=config, timeout=httpx.Timeout(timeout))
        self._has_projects: bool | None = None

    def _supports_projects(self) -> bool:
        """Check if the cluster supports OpenShift Projects (cached).

        Sends GET /apis/project.openshift.io/v1/projects?limit=1.
        On OpenShift this returns 200 (API group registered).
        On vanilla K8s this returns 404 (API group unknown).
        """
        if self._has_projects is None:
            try:
                next(iter(self._client.list(_Project, chunk_size=1)), None)
                self._has_projects = True
            except ApiError as e:
                if e.status.code == _HTTP_FORBIDDEN:
                    self._has_projects = True
                elif e.status.code == _HTTP_NOT_FOUND:
                    self._has_projects = False
                else:
                    raise from_api_error(e) from e
        return self._has_projects

    def _use_project_api(self, name: str) -> bool:
        """Decide whether to use the Project API for this namespace.

        Mirrors oc.py's _use_oc_project(): use Project API when the cluster
        supports it AND the name doesn't start with 'openshift-' (those
        cannot be created via the Project API).
        """
        return self._supports_projects() and not name.startswith("openshift-")

    @invoke_with_hooks(
        lambda self: KubernetesApiCallContext(
            method="namespaces.get", verb="GET", id=self._server
        )
    )
    def get_namespace(self, name: str) -> Namespace:
        """Get a namespace by name.

        Args:
            name: Namespace name

        Returns:
            The Namespace object

        Raises:
            NotFoundError: If the namespace does not exist
            KubernetesApiError: On other API errors
        """
        try:
            return self._client.get(Namespace, name=name)
        except ApiError as e:
            raise from_api_error(e) from e

    @invoke_with_hooks(
        lambda self: KubernetesApiCallContext(
            method="namespaces.list", verb="GET", id=self._server
        )
    )
    def list_namespaces(self) -> list[Namespace]:
        """List all namespaces.

        On OpenShift, every Project creates a corresponding Namespace,
        so listing Namespaces returns Projects too.

        Returns:
            List of Namespace objects
        """
        try:
            return list(self._client.list(Namespace))
        except ApiError as e:
            raise from_api_error(e) from e

    @invoke_with_hooks(
        lambda self: KubernetesApiCallContext(
            method="namespaces.exists", verb="GET", id=self._server
        )
    )
    def namespace_exists(self, name: str) -> bool:
        """Check if a namespace/project exists.

        Uses OpenShift Project API when available, falls back to Namespace.

        Args:
            name: Namespace name

        Returns:
            True if the namespace exists, False otherwise
        """
        resource = _Project if self._use_project_api(name) else Namespace
        try:
            self._client.get(resource, name=name)
        except ApiError as e:
            if e.status.code == _HTTP_NOT_FOUND:
                return False
            raise from_api_error(e) from e
        return True

    @invoke_with_hooks(
        lambda self: KubernetesApiCallContext(
            method="namespaces.create", verb="POST", id=self._server
        )
    )
    def create_namespace(self, name: str) -> Namespace:
        """Create a namespace/project (idempotent — 409 is silently handled).

        Uses OpenShift Project API when available (triggers
        ProjectRequestTemplate), falls back to plain Namespace.

        Args:
            name: Namespace name to create

        Returns:
            The created or existing Namespace object
        """
        if self._use_project_api(name):
            return self._create_project(name)
        return self._create_namespace(name)

    def _create_project(self, name: str) -> Namespace:
        """Create via OpenShift Project API, return as Namespace."""
        project = _Project(metadata=ObjectMeta(name=name))
        try:
            self._client.create(project)
        except ApiError as e:
            if e.status.code != _HTTP_CONFLICT:
                raise from_api_error(e) from e
        try:
            return self._client.get(Namespace, name=name)
        except ApiError as e:
            raise from_api_error(e) from e

    def _create_namespace(self, name: str) -> Namespace:
        """Create via plain Kubernetes Namespace API."""
        ns = Namespace(metadata=ObjectMeta(name=name))
        try:
            return self._client.create(ns)
        except ApiError as e:
            if e.status.code == _HTTP_CONFLICT:
                try:
                    return self._client.get(Namespace, name=name)
                except ApiError as get_e:
                    raise from_api_error(get_e) from get_e
            raise from_api_error(e) from e

    @invoke_with_hooks(
        lambda self: KubernetesApiCallContext(
            method="namespaces.delete", verb="DELETE", id=self._server
        )
    )
    def delete_namespace(self, name: str) -> None:
        """Delete a namespace/project (idempotent — 404 is silently ignored).

        Uses OpenShift Project API when available, falls back to Namespace.

        Args:
            name: Namespace name to delete
        """
        resource = _Project if self._use_project_api(name) else Namespace
        try:
            self._client.delete(resource, name=name)
        except ApiError as e:
            if e.status.code == _HTTP_NOT_FOUND:
                return
            raise from_api_error(e) from e

    def close(self) -> None:
        """Release the underlying lightkube client and httpx connection pool.

        Workaround: lightkube has no public close() on the sync client.
        https://github.com/gtsystem/lightkube/issues/144
        """
        if client := getattr(self, "_client", None):
            client._client._client.close()  # type: ignore[attr-defined]  # noqa: SLF001
            del self._client

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
