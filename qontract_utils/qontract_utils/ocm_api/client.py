"""OCM API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
logging via hooks (ADR-006), on top of the wire-format models in _raw_client.py.
"""

from __future__ import annotations

import contextvars
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.ocm_api._raw_client import (
    RawIdentityProvider,
    RawIdentityProviderOidc,
    RawMachinePool,
    RawNodePool,
    RawOcmClient,
    RawOrganizationLabel,
    RawSubscriptionLabel,
    RawTaint,
)
from qontract_utils.ocm_api.exceptions import OcmUserRoleNotLinkedError
from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmClusterGroup,
    OcmIdentityProvider,
    OcmIdentityProviderOidc,
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
    OcmMachinePool,
    OcmMachinePoolAutoscaling,
    OcmNodePool,
    OcmNodePoolAutoscaling,
    OcmNodePoolAws,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
    OcmTaint,
)
from qontract_utils.user_agent import DEFAULT_USER_AGENT

if TYPE_CHECKING:
    from qontract_utils.ocm_api._raw_client import RawCluster, RawSubscription
    from qontract_utils.ocm_api.search_filters import Filter

logger = structlog.get_logger(__name__)

TIMEOUT = 60.0
MAX_RETRIES = 3
CHUNK_SIZE = 100
HTTP_BAD_REQUEST = 400

# Prometheus metrics
ocm_request = Counter(
    "qontract_reconcile_external_api_ocm_requests_total",
    "Total number of OCM API requests",
    ["method", "verb"],
)

ocm_request_duration = Histogram(
    "qontract_reconcile_external_api_ocm_request_duration_seconds",
    "OCM API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


@dataclass(frozen=True)
class OcmApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "labels.list")
        verb: HTTP verb (e.g., "GET")
        client_id: OCM access token client id (identifies the calling org)
    """

    method: str
    verb: str
    client_id: str


def _metrics_hook(context: OcmApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    ocm_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: OcmApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: OcmApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    ocm_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: OcmApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "API request",
        method=context.method,
        verb=context.verb,
        client_id=context.client_id,
    )


def _raise_for_user_role_not_linked(
    exc: httpx2.HTTPStatusError, *, cluster_id: str
) -> None:
    """Re-raise as OcmUserRoleNotLinkedError if exc is OCM's UserRoleIsNotLinkedToAccount 400.

    Returns normally (letting the caller re-raise the original exc) for any other
    status code, an unparseable body, or a 400 with a different Error_Key - this
    carve-out must only ever match the one specific, tenant-actionable error it
    names, never 400s in general.
    """
    if exc.response.status_code != HTTP_BAD_REQUEST:
        return
    try:
        body = exc.response.json()
    except json.JSONDecodeError:
        return
    if not isinstance(body, dict):
        return
    details = body.get("details", [])
    if not isinstance(details, list):
        return
    if any(
        isinstance(d, dict) and d.get("Error_Key") == "UserRoleIsNotLinkedToAccount"
        for d in details
    ):
        raise OcmUserRoleNotLinkedError(
            cluster_id=cluster_id, reason=body.get("reason", str(exc))
        ) from exc


def _fetch_access_token(
    access_token_url: str,
    access_token_client_id: str,
    access_token_client_secret: str,
    timeout: float,
    user_agent: str,
) -> str:
    response = httpx2.post(
        access_token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": access_token_client_id,
            "client_secret": access_token_client_secret,
        },
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


@with_hooks(
    hooks=Hooks(
        pre_hooks=[
            _metrics_hook,
            _request_log_hook,
            _latency_start_hook,
        ],
        post_hooks=[_latency_end_hook],
    )
)
class OcmApi:
    """Stateless OCM API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Covers exactly the OCM
    operations needed by reconcile/rhidp/sso_client: listing labels, subscriptions,
    and clusters. Composition of these into a higher-level "which clusters need
    what auth config" view is business logic and belongs in a later phase.

    The OAuth2 client-credentials bearer token is fetched once at construction
    (mirroring reconcile/utils/ocm_base_client.py today). Each instance owns its own
    httpx2.Client - use as a context manager (or call close()) to release it when done.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive OcmApiCallContext with method, verb, client_id
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        url: str,
        access_token_url: str,
        access_token_client_id: str,
        access_token_client_secret: str,
        hooks: Hooks | None = None,
        timeout: float = TIMEOUT,
        max_retries: int = MAX_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        """Initialize the OCM API client.

        Args:
            url: OCM environment base URL (e.g., "https://api.openshift.com")
            access_token_url: OAuth2 token endpoint (Red Hat SSO, client-credentials grant)
            access_token_client_id: OAuth2 client id
            access_token_client_secret: OAuth2 client secret (already resolved plaintext)
            timeout: API request timeout in seconds (default: 60)
            max_retries: number of transport-level retries for failed requests (default: 3)
            user_agent: User-Agent header sent with every request, including the
                OAuth token exchange. Defaults to identifying qontract-utils itself;
                callers embedded in a larger service (e.g. qontract-api) should pass
                their own app name/version so OCM can attribute traffic to the actual
                caller.
            hooks: Optional custom hooks to merge with built-in hooks. Not read here -
                @with_hooks intercepts and merges it into self._hooks before this body runs.
        """
        _ = hooks
        self.url = url
        self.access_token_client_id = access_token_client_id
        access_token = _fetch_access_token(
            access_token_url,
            access_token_client_id,
            access_token_client_secret,
            timeout,
            user_agent,
        )
        self._client = httpx2.Client(
            base_url=url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": user_agent,
            },
            timeout=timeout,
            transport=httpx2.HTTPTransport(retries=max_retries),
        )
        self._raw = RawOcmClient(self._client)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="labels.list", verb="GET", client_id=self.access_token_client_id
        )
    )
    def get_labels(
        self, search_filter: Filter
    ) -> list[OcmSubscriptionLabel | OcmOrganizationLabel]:
        """List OCM labels matching the given filter."""
        return [
            _label_from_raw(label)
            for label in self._raw.get_labels(
                search=search_filter.render(), order_by="created_at"
            )
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="subscriptions.list",
            verb="GET",
            client_id=self.access_token_client_id,
        )
    )
    def get_subscriptions(self, search_filter: Filter) -> dict[str, OcmSubscription]:
        """List OCM subscriptions matching the given filter, keyed by subscription id.

        The filter is chunked by "id" in groups of CHUNK_SIZE, matching OCM's
        practical limits on `search` value-list length.
        """
        subscriptions: dict[str, OcmSubscription] = {}
        for filter_chunk in search_filter.chunk_by(
            "id", CHUNK_SIZE, ignore_missing=True
        ):
            for subscription in self._raw.get_subscriptions(
                search=filter_chunk.render(),
                order_by="id",
                fetch_labels=True,
                fetch_capabilities=True,
            ):
                mapped = _subscription_from_raw(subscription)
                subscriptions[mapped.id] = mapped
        return subscriptions

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="clusters.list", verb="GET", client_id=self.access_token_client_id
        )
    )
    def get_clusters(self, search_filter: Filter) -> list[OcmCluster]:
        """List OCM clusters matching the given filter."""
        return [
            _cluster_from_raw(cluster)
            for cluster in self._raw.get_clusters(
                search=search_filter.render(), order="creation_timestamp"
            )
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="identity_providers.list",
            verb="GET",
            client_id=self.access_token_client_id,
        )
    )
    def get_identity_providers(
        self, cluster_id: str
    ) -> list[OcmIdentityProvider | OcmIdentityProviderOidc]:
        """List identity providers configured on a cluster."""
        return [
            _identity_provider_from_raw(item)
            for item in self._raw.get_identity_providers(cluster_id=cluster_id)
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="identity_providers.create",
            verb="POST",
            client_id=self.access_token_client_id,
        )
    )
    def create_identity_provider(
        self, cluster_id: str, idp: OcmIdentityProviderOidc
    ) -> OcmIdentityProviderOidc:
        """Create an OIDC identity provider on a cluster.

        Raises OcmUserRoleNotLinkedError (instead of the generic HTTPStatusError) if
        OCM rejects this with UserRoleIsNotLinkedToAccount - a tenant-side STS
        misconfiguration callers may want to handle specially (see APPSRE-15204).
        """
        try:
            raw = self._raw.create_identity_provider(
                cluster_id=cluster_id,
                body=idp.model_dump(exclude_none=True, exclude={"id"}),
            )
        except httpx2.HTTPStatusError as exc:
            _raise_for_user_role_not_linked(exc, cluster_id=cluster_id)
            raise
        return _oidc_identity_provider_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="identity_providers.update",
            verb="PATCH",
            client_id=self.access_token_client_id,
        )
    )
    def update_identity_provider(
        self, cluster_id: str, idp_id: str, idp: OcmIdentityProviderOidc
    ) -> OcmIdentityProviderOidc:
        """Update an existing OIDC identity provider.

        Name is immutable on OCM, so it is excluded from the request body. Raises
        OcmUserRoleNotLinkedError (instead of the generic HTTPStatusError) if OCM
        rejects this with UserRoleIsNotLinkedToAccount - see create_identity_provider.
        """
        try:
            raw = self._raw.update_identity_provider(
                cluster_id=cluster_id,
                idp_id=idp_id,
                body=idp.model_dump(exclude_none=True, exclude={"id", "name"}),
            )
        except httpx2.HTTPStatusError as exc:
            _raise_for_user_role_not_linked(exc, cluster_id=cluster_id)
            raise
        return _oidc_identity_provider_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="identity_providers.delete",
            verb="DELETE",
            client_id=self.access_token_client_id,
        )
    )
    def delete_identity_provider(self, cluster_id: str, idp_id: str) -> None:
        """Delete an identity provider from a cluster."""
        self._raw.delete_identity_provider(cluster_id=cluster_id, idp_id=idp_id)

    # Cluster Group operations
    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="groups.list",
            verb="GET",
            client_id=self.access_token_client_id,
        )
    )
    def get_cluster_groups(self, cluster_id: str) -> list[OcmClusterGroup]:
        """List all groups on a cluster with their users."""
        return [
            OcmClusterGroup(
                id=group.id,
                users=[user.id for user in (group.users.items if group.users else [])],
            )
            for group in self._raw.get_cluster_groups(cluster_id=cluster_id)
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="groups.add_user",
            verb="POST",
            client_id=self.access_token_client_id,
        )
    )
    def add_user_to_group(self, cluster_id: str, group_id: str, user_id: str) -> None:
        """Add a user to a cluster group."""
        self._raw.add_user_to_group(
            cluster_id=cluster_id, group_id=group_id, user_id=user_id
        )

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="groups.delete_user",
            verb="DELETE",
            client_id=self.access_token_client_id,
        )
    )
    def delete_user_from_group(
        self, cluster_id: str, group_id: str, user_id: str
    ) -> None:
        """Remove a user from a cluster group."""
        self._raw.delete_user_from_group(
            cluster_id=cluster_id, group_id=group_id, user_id=user_id
        )

    # Machine Pool operations (OSD / ROSA classic clusters)
    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="machine_pools.list",
            verb="GET",
            client_id=self.access_token_client_id,
        )
    )
    def get_machine_pools(self, cluster_id: str) -> list[OcmMachinePool]:
        """List all machine pools on a cluster."""
        return [
            _machine_pool_from_raw(pool)
            for pool in self._raw.get_machine_pools(cluster_id=cluster_id)
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="machine_pools.create",
            verb="POST",
            client_id=self.access_token_client_id,
        )
    )
    def create_machine_pool(
        self, cluster_id: str, pool: OcmMachinePool
    ) -> OcmMachinePool:
        """Create a machine pool on a cluster.

        The pool id is client-chosen in OCM (unlike most other resources), so it
        is included in the request body.
        """
        raw = self._raw.create_machine_pool(
            cluster_id=cluster_id,
            body=pool.model_dump(exclude_none=True),
        )
        return _machine_pool_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="machine_pools.update",
            verb="PATCH",
            client_id=self.access_token_client_id,
        )
    )
    def update_machine_pool(
        self, cluster_id: str, pool: OcmMachinePool
    ) -> OcmMachinePool:
        """Update an existing machine pool on a cluster.

        instance_type is immutable on OCM, so it is excluded from the request
        body (the pool id travels in the URL path). Callers are expected to
        detect instance_type diffs themselves and fail instead of calling this.
        """
        raw = self._raw.update_machine_pool(
            cluster_id=cluster_id,
            machine_pool_id=pool.id,
            body=_machine_pool_update_body(pool),
        )
        return _machine_pool_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="machine_pools.delete",
            verb="DELETE",
            client_id=self.access_token_client_id,
        )
    )
    def delete_machine_pool(self, cluster_id: str, machine_pool_id: str) -> None:
        """Delete a machine pool from a cluster."""
        self._raw.delete_machine_pool(
            cluster_id=cluster_id, machine_pool_id=machine_pool_id
        )

    # Node Pool operations (HyperShift / ROSA HCP clusters)
    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="node_pools.list",
            verb="GET",
            client_id=self.access_token_client_id,
        )
    )
    def get_node_pools(self, cluster_id: str) -> list[OcmNodePool]:
        """List all node pools on a cluster."""
        return [
            _node_pool_from_raw(pool)
            for pool in self._raw.get_node_pools(cluster_id=cluster_id)
        ]

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="node_pools.create",
            verb="POST",
            client_id=self.access_token_client_id,
        )
    )
    def create_node_pool(self, cluster_id: str, pool: OcmNodePool) -> OcmNodePool:
        """Create a node pool on a cluster.

        The pool id is client-chosen in OCM (unlike most other resources), so it
        is included in the request body.
        """
        raw = self._raw.create_node_pool(
            cluster_id=cluster_id,
            body=pool.model_dump(exclude_none=True),
        )
        return _node_pool_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="node_pools.update",
            verb="PATCH",
            client_id=self.access_token_client_id,
        )
    )
    def update_node_pool(self, cluster_id: str, pool: OcmNodePool) -> OcmNodePool:
        """Update an existing node pool on a cluster.

        aws_node_pool (instance_type) and subnet are immutable on OCM, so they
        are excluded from the request body (the pool id travels in the URL
        path). Callers are expected to detect those diffs themselves and fail
        instead of calling this.
        """
        raw = self._raw.update_node_pool(
            cluster_id=cluster_id,
            node_pool_id=pool.id,
            body=_node_pool_update_body(pool),
        )
        return _node_pool_from_raw(raw)

    @invoke_with_hooks(
        lambda self: OcmApiCallContext(
            method="node_pools.delete",
            verb="DELETE",
            client_id=self.access_token_client_id,
        )
    )
    def delete_node_pool(self, cluster_id: str, node_pool_id: str) -> None:
        """Delete a node pool from a cluster."""
        self._raw.delete_node_pool(cluster_id=cluster_id, node_pool_id=node_pool_id)


def _label_from_raw(
    label: RawSubscriptionLabel | RawOrganizationLabel,
) -> OcmSubscriptionLabel | OcmOrganizationLabel:
    match label:
        case RawSubscriptionLabel():
            return OcmSubscriptionLabel(
                key=label.key, value=label.value, subscription_id=label.subscription_id
            )
        case RawOrganizationLabel():
            return OcmOrganizationLabel(
                key=label.key, value=label.value, organization_id=label.organization_id
            )


def _subscription_from_raw(subscription: RawSubscription) -> OcmSubscription:
    return OcmSubscription(
        id=subscription.id,
        organization_id=subscription.organization_id,
        status=subscription.status,
        managed=subscription.managed,
    )


def _cluster_from_raw(cluster: RawCluster) -> OcmCluster:
    return OcmCluster(
        id=cluster.id,
        name=cluster.name,
        subscription_id=cluster.subscription.id,
        console_url=cluster.console.url if cluster.console else None,
        external_auth_enabled=(
            cluster.external_auth_config.enabled
            if cluster.external_auth_config
            else False
        ),
    )


def _identity_provider_from_raw(
    raw: RawIdentityProviderOidc | RawIdentityProvider,
) -> OcmIdentityProvider | OcmIdentityProviderOidc:
    if isinstance(raw, RawIdentityProviderOidc):
        return _oidc_identity_provider_from_raw(raw)
    return OcmIdentityProvider(type=raw.type, name=raw.name, id=raw.id)


def _oidc_identity_provider_from_raw(
    raw: RawIdentityProviderOidc,
) -> OcmIdentityProviderOidc:
    return OcmIdentityProviderOidc(
        name=raw.name,
        id=raw.id,
        mapping_method=raw.mapping_method,
        open_id=OcmIdentityProviderOidcOpenId(
            client_id=raw.open_id.client_id,
            client_secret=raw.open_id.client_secret,
            issuer=raw.open_id.issuer,
            claims=OcmIdentityProviderOidcOpenIdClaims(
                email=raw.open_id.claims.email,
                name=raw.open_id.claims.name,
                preferred_username=raw.open_id.claims.preferred_username,
                groups=raw.open_id.claims.groups,
            ),
        ),
    )


def _taints_from_raw(raw: list[RawTaint] | None) -> list[OcmTaint] | None:
    """Map raw wire taints to domain taints, preserving None."""
    if raw is None:
        return None
    return [OcmTaint(key=t.key, value=t.value, effect=t.effect) for t in raw]


def _machine_pool_from_raw(raw: RawMachinePool) -> OcmMachinePool:
    """Map a raw machine pool wire object to the domain model."""
    return OcmMachinePool(
        id=raw.id,
        instance_type=raw.instance_type,
        replicas=raw.replicas,
        autoscaling=(
            OcmMachinePoolAutoscaling(
                min_replicas=raw.autoscaling.min_replicas,
                max_replicas=raw.autoscaling.max_replicas,
            )
            if raw.autoscaling
            else None
        ),
        labels=raw.labels,
        taints=_taints_from_raw(raw.taints),
    )


def _node_pool_from_raw(raw: RawNodePool) -> OcmNodePool:
    """Map a raw node pool wire object to the domain model."""
    return OcmNodePool(
        id=raw.id,
        aws_node_pool=OcmNodePoolAws(instance_type=raw.aws_node_pool.instance_type),
        replicas=raw.replicas,
        autoscaling=(
            OcmNodePoolAutoscaling(
                min_replica=raw.autoscaling.min_replica,
                max_replica=raw.autoscaling.max_replica,
            )
            if raw.autoscaling
            else None
        ),
        labels=raw.labels,
        taints=_taints_from_raw(raw.taints),
        subnet=raw.subnet,
    )


def _apply_legacy_update_contract(
    body: dict[str, Any], pool: OcmMachinePool | OcmNodePool
) -> dict[str, Any]:
    """Apply the legacy update-body wire contract to a dumped pool.

    Mirrors reconcile/utils/ocm/ocm.py + reconcile/ocm_machine_pools.py, which
    have sent this exact shape to OCM in production since 2021:

    - replicas and autoscaling are BOTH always present, with an explicit null
      for the inactive one, so fixed <-> autoscaling mode transitions are
      explicit on the wire
    - labels are always sent, as {} when empty, so a PATCH can clear them
      (the legacy OCM client re-added labels unconditionally)
    - taints are omitted when empty (the legacy client deleted them)
    """
    body["labels"] = pool.labels or {}
    if not pool.taints:
        del body["taints"]
    return body


def _machine_pool_update_body(pool: OcmMachinePool) -> dict[str, Any]:
    """Build the PATCH body for a machine pool update.

    Excludes id (travels in the URL path) and instance_type (immutable on
    OCM), then applies the shared legacy update-body contract.
    """
    body = pool.model_dump(exclude={"id", "instance_type"})
    return _apply_legacy_update_contract(body, pool)


def _node_pool_update_body(pool: OcmNodePool) -> dict[str, Any]:
    """Build the PATCH body for a node pool update.

    Excludes id (travels in the URL path), aws_node_pool and subnet (immutable
    on OCM), then applies the shared legacy update-body contract.
    """
    body = pool.model_dump(exclude={"id", "aws_node_pool", "subnet"})
    return _apply_legacy_update_contract(body, pool)
