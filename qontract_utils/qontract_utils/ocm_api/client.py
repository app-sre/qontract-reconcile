"""OCM API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
logging via hooks (ADR-006), on top of the wire-format models in _raw_client.py.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

import httpx2
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
from qontract_utils.ocm_api._raw_client import (
    RawIdentityProvider,
    RawIdentityProviderOidc,
    RawOcmClient,
    RawOrganizationLabel,
    RawSubscriptionLabel,
)
from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmClusterGroup,
    OcmIdentityProvider,
    OcmIdentityProviderOidc,
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)
from qontract_utils.user_agent import DEFAULT_USER_AGENT

if TYPE_CHECKING:
    from qontract_utils.ocm_api._raw_client import RawCluster, RawSubscription
    from qontract_utils.ocm_api.search_filters import Filter

logger = structlog.get_logger(__name__)

TIMEOUT = 60.0
MAX_RETRIES = 3
CHUNK_SIZE = 100

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
        """Create an OIDC identity provider on a cluster."""
        raw = self._raw.create_identity_provider(
            cluster_id=cluster_id,
            body=idp.model_dump(exclude_none=True, exclude={"id"}),
        )
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

        Name is immutable on OCM, so it is excluded from the request body.
        """
        raw = self._raw.update_identity_provider(
            cluster_id=cluster_id,
            idp_id=idp_id,
            body=idp.model_dump(exclude_none=True, exclude={"id", "name"}),
        )
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
