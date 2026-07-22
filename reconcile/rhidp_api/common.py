"""Shared GraphQL queries and RHIDP label constants for reconcile/rhidp_api integrations.

Ported from reconcile/rhidp/common.py (not imported) - reconcile/rhidp/ is meant to be
deleted once the qontract-api migration is complete, so nothing here may depend on it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.rhidp.organizations import (
    OpenShiftClusterManagerV1,
)
from reconcile.gql_definitions.rhidp.organizations import (
    query as ocm_orgs_query,
)
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key

if TYPE_CHECKING:
    from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment

# Generates label keys for rhidp, compliant with the naming schema defined in
# https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
RHIDP_NAMESPACE_LABEL_KEY = sre_capability_label_key("rhidp")
STATUS_LABEL_KEY = sre_capability_label_key("rhidp", "status")
ISSUER_LABEL_KEY = sre_capability_label_key("rhidp", "issuer")
AUTH_NAME_LABEL_KEY = sre_capability_label_key("rhidp", "name")
GROUP_FILTER_REGEX_LABEL_KEY = sre_capability_label_key("rhidp", "group-filter-regex")


class StatusValue(StrEnum):
    # rhidp and oidc are enabled
    ENABLED = "enabled"
    # rhidp and oidc are disabled
    DISABLED = "disabled"
    # rhidp is enabled and oidc will delete all other configured idps
    ENFORCED = "enforced"
    # rhidp is enabled and oidc is skipped
    RHIDP_ONLY = "sso-client-only"


def get_ocm_environments(env_name: str | None) -> list[OCMEnvironment]:
    return ocm_environment_query(
        gql.get_api().query,
        variables={"name": env_name} if env_name else None,
    ).environments


def get_ocm_orgs_from_env(
    env_name: str, int_name: str
) -> list[OpenShiftClusterManagerV1]:
    orgs = ocm_orgs_query(
        gql.get_api().query,
    ).organizations
    return [
        org
        for org in orgs or []
        if integration_is_enabled(int_name, org) and org.environment.name == env_name
    ]
