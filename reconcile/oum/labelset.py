from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from reconcile.oum.models import ExternalGroupRef
from reconcile.utils.models import CSV
from reconcile.utils.ocm import sre_capability_labels
from reconcile.utils.ocm.cluster_groups import OCMClusterGroupId
from reconcile.utils.ocm.labels import LabelContainer


class _GroupMappingLabelset(BaseModel):
    """
    Parses, represents and validates a set of provider labels for the user management SRE capability.

    The full qualified label names supported by the standalone user management are defined as follows:

    * sre-capabilities.user-mgmt.$provider.authz.dedicated-admins: group1,group2
    * sre-capabilities.user-mgmt.$provider.authz.cluster-admins: group3,group4

    This labelset is processed per provider so it defines labelnames without
    the sre-capabilities.user-mgmt.$provider prefix.
    """

    authz_roles: Optional[dict[str, CSV]] = sre_capability_labels.labelset_groupfield(
        group_prefix="authz."
    )


def build_cluster_config_from_labels(
    provider: str,
    org_labels: LabelContainer,
    subscription_labels: LabelContainer,
) -> dict[OCMClusterGroupId, list[ExternalGroupRef]]:
    """
    Extract the role-group mappings from the given organization and subscription label.

    The label keys are expected to be stripped of the capability prefix and
    external group provider prefix, resulting in the key names used in the
    GroupMappingLabelset model.
    """
    role_group_mapping: dict[OCMClusterGroupId, list[ExternalGroupRef]] = defaultdict(
        list
    )

    # turn org labels and subscription labels individually into a labelset
    for labels in [org_labels, subscription_labels]:
        labelset = sre_capability_labels.build_labelset(labels, _GroupMappingLabelset)
        for ocm_group_name, external_groups in (labelset.authz_roles or {}).items():
            for external_group_id in external_groups:
                role_group_mapping[OCMClusterGroupId(ocm_group_name)].append(
                    ExternalGroupRef(provider=provider, group_id=external_group_id)
                )

    return role_group_mapping
