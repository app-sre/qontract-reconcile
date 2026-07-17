"""OCM API client and models.

This package provides a stateless OCM (OpenShift Cluster Manager) API client
following the three-layer architecture pattern (ADR-014), covering exactly the
operations needed by reconcile/rhidp/sso_client.

Layer 1 (Pure Communication):
- OcmApi: Stateless API client with hooks for metrics and logging
- Models: Pydantic domain models for labels, subscriptions, and clusters

Hook System (ADR-006):
- OcmApiCallContext: Context passed to hooks
- pre_hooks: Hook system for metrics, logging, latency

Example:
    >>> from qontract_utils.ocm_api import OcmApi, subscription_label_filter
    >>> api = OcmApi(
    ...     url="https://api.openshift.com",
    ...     access_token_url="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
    ...     access_token_client_id="...",
    ...     access_token_client_secret="...",
    ... )
    >>> labels = api.get_labels(subscription_label_filter().like("key", "sre-capabilities.rhidp%"))
"""

from qontract_utils.ocm_api.client import TIMEOUT, OcmApi, OcmApiCallContext
from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)
from qontract_utils.ocm_api.search_filters import (
    ACTIVE_SUBSCRIPTION_STATES,
    PRODUCT_ID_OSD,
    PRODUCT_ID_ROSA,
    Filter,
    InvalidChunkRequestError,
    InvalidFilterError,
    build_subscription_filter,
    cluster_ready_for_app_interface,
    organization_label_filter,
    subscription_label_filter,
)

__all__ = [
    "ACTIVE_SUBSCRIPTION_STATES",
    "PRODUCT_ID_OSD",
    "PRODUCT_ID_ROSA",
    "TIMEOUT",
    "Filter",
    "InvalidChunkRequestError",
    "InvalidFilterError",
    "OcmApi",
    "OcmApiCallContext",
    "OcmCluster",
    "OcmOrganizationLabel",
    "OcmSubscription",
    "OcmSubscriptionLabel",
    "build_subscription_filter",
    "cluster_ready_for_app_interface",
    "organization_label_filter",
    "subscription_label_filter",
]
