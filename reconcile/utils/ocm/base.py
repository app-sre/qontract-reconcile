from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import Enum, StrEnum
from typing import (
    TypeVar,
)

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.utils.aws_helper import get_account_uid_from_arn, get_role_name_from_arn
from reconcile.utils.semver_helper import parse_semver

LabelSetTypeVar = TypeVar("LabelSetTypeVar", bound=BaseModel)
ACTIVE_SUBSCRIPTION_STATES = {"Active", "Reserved"}
CAPABILITY_MANAGE_CLUSTER_ADMIN = "capability.cluster.manage_cluster_admin"


class OCMCollectionLink(BaseModel):
    kind: str | None = None
    href: str | None = None


class OCMModelLink(OCMCollectionLink):
    id: str


class OCMAddonVersion(BaseModel):
    id: str
    href: str
    available_upgrades: list[str]


class OCMAddonInstallation(BaseModel):
    kind: str = "AddOnInstallation"
    id: str
    addon: OCMModelLink
    state: str
    addon_version: OCMAddonVersion


class OCMVersionGate(BaseModel):
    kind: str = "VersionGate"
    id: str
    version_raw_id_prefix: str
    sts_only: bool
    label: str
    """
    the label field holds a readable name for a verion gate, e.g.
    - api.openshift.com/gate-sts
    - api.openshift.com/gate-ocp
    """


class OCMClusterGroupId(Enum):
    """
    Cluster groups managable by OCM.
    """

    DEDICATED_ADMINS = "dedicated-admins"
    CLUSTER_ADMINS = "cluster-admins"

    @classmethod
    def values(cls) -> list[str]:
        return [group.value for group in cls]


class OCMClusterUser(BaseModel):
    """
    Represents a cluster user.
    """

    id: str
    """
    The id represents the user name.
    """

    href: str | None = None
    kind: str = "User"


class OCMClusterUserList(BaseModel):
    """
    Represents a list of cluster users.
    """

    kind: str = "UserList"
    href: str | None = None
    items: list[OCMClusterUser]


class OCMClusterGroup(BaseModel):
    """
    Represents a cluster group.
    """

    id: OCMClusterGroupId
    href: str | None = None
    users: OCMClusterUserList | None = None

    def user_ids(self) -> set[str]:
        """
        Returns a set of user ids.
        """
        if self.users is None:
            return set()
        return {user.id for user in self.users.items}


class OCMClusterState(Enum):
    ERROR = "error"
    HIBERNATING = "hibernating"
    INSTALLING = "installing"
    PENING = "pending"
    POWERING_DOWN = "powering_down"
    READY = "ready"
    RESUMING = "resuming"
    UNINSTALLING = "uninstalling"
    UNKNOWN = "unknown"
    VALIDATING = "validating"
    WAITING = "waiting"


class OCMClusterFlag(BaseModel):
    enabled: bool


class OCMClusterAWSOperatorRole(BaseModel):
    id: str
    name: str
    namespace: str
    role_arn: str
    service_account: str


class OCMAWSSTS(OCMClusterFlag):
    role_arn: str | None
    support_role_arn: str | None
    oidc_endpoint_url: str | None
    operator_iam_roles: list[OCMClusterAWSOperatorRole] | None
    instance_iam_roles: dict[str, str] | None
    operator_role_prefix: str | None


class OCMClusterAWSSettings(BaseModel):
    sts: OCMAWSSTS | None

    @property
    def sts_enabled(self) -> bool:
        return self.sts is not None and self.sts.enabled

    @property
    def aws_account_id(self) -> str:
        return get_account_uid_from_arn(self.account_roles[0])

    @property
    def account_roles(self) -> list[str]:
        if not self.sts or not self.sts.enabled:
            return []
        roles = []
        if self.sts.role_arn:
            roles.append(self.sts.role_arn)
        if self.sts.support_role_arn:
            roles.append(self.sts.support_role_arn)
        roles.extend(
            instance_iam_role
            for instance_iam_role in (self.sts.instance_iam_roles or {}).values()
        )
        return roles

    @property
    def account_role_prefix(self) -> str | None:
        INSTALLER_ROLE_BASE_NAME = "-Installer-Role"
        installer_role_arn = self.sts.role_arn if self.sts else None
        if installer_role_arn and installer_role_arn.endswith(INSTALLER_ROLE_BASE_NAME):
            installer_role_name = get_role_name_from_arn(installer_role_arn)
            return installer_role_name.removesuffix(INSTALLER_ROLE_BASE_NAME)
        return None

    @property
    def operator_roles(self) -> list[str]:
        if not self.sts:
            return []
        return [role.role_arn for role in self.sts.operator_iam_roles or []]


class OCMClusterVersion(BaseModel):
    id: str
    raw_id: str
    channel_group: str
    available_upgrades: list[str] = Field(default_factory=list)


class OCMClusterConsole(BaseModel):
    url: str


class OCMClusterAPI(BaseModel):
    url: str
    listening: str


class OCMClusterDns(BaseModel):
    base_domain: str


class OCMExternalConfiguration(BaseModel):
    syncsets: dict


PRODUCT_ID_OSD = "osd"
PRODUCT_ID_ROSA = "rosa"


class ProvisionShard(BaseModel):
    kind: str = "ProvisionShard"
    id: str


class ClusterManagementReference(BaseModel):
    cluster_id: str
    href: str


class FleetManagerServiceCluster(BaseModel):
    kind: str = "ServiceCluster"

    """
    Using OSDFleetManager API, which has different object ids.
    https://api.openshift.com/?urls.primaryName=OSD%20Fleet%20Manager%20service
    """
    cluster_management_reference: ClusterManagementReference
    provision_shard_reference: OCMModelLink


class OCMCluster(BaseModel):
    kind: str = "Cluster"
    id: str
    external_id: str
    """
    This is sometimes also called the cluster UUID.
    """

    name: str
    display_name: str

    managed: bool
    state: OCMClusterState

    subscription: OCMModelLink
    region: OCMModelLink
    cloud_provider: OCMModelLink
    product: OCMModelLink
    identity_providers: OCMCollectionLink

    aws: OCMClusterAWSSettings | None

    version: OCMClusterVersion

    hypershift: OCMClusterFlag

    console: OCMClusterConsole | None

    api: OCMClusterAPI | None

    dns: OCMClusterDns | None

    external_configuration: OCMExternalConfiguration | None

    def minor_version(self) -> str:
        version_info = parse_semver(self.version.raw_id)
        return f"{version_info.major}.{version_info.minor}"

    def available_upgrades(self) -> list[str]:
        return self.version.available_upgrades

    def is_osd(self) -> bool:
        return self.product.id == PRODUCT_ID_OSD

    def is_rosa(self) -> bool:
        return self.product.id == PRODUCT_ID_ROSA

    def is_rosa_classic(self) -> bool:
        return self.product.id == PRODUCT_ID_ROSA and not self.hypershift.enabled

    def is_rosa_hypershift(self) -> bool:
        return self.product.id == PRODUCT_ID_ROSA and self.hypershift.enabled

    def is_sts(self) -> bool:
        return self.aws.sts_enabled if self.aws else False

    def ready(self) -> bool:
        return (
            self.managed
            and self.state == OCMClusterState.READY
            and self.product.id in {PRODUCT_ID_OSD, PRODUCT_ID_ROSA}
        )

    @property
    def console_url(self) -> str | None:
        return self.console.url if self.console else None

    @property
    def api_url(self) -> str | None:
        return self.api.url if self.api else None

    @property
    def base_domain(self) -> str | None:
        return self.dns.base_domain if self.dns else None


class OCMLabel(BaseModel):
    """
    Represents a general label without any type specific information.
    See subclasses for type specific information.
    """

    id: str
    internal: bool
    updated_at: datetime
    created_at: datetime
    href: str
    key: str
    value: str
    type: str
    """
    The type of the label, e.g. Subscription, Organization, Account.
    See subclasses.
    """

    def __repr__(self) -> str:
        return f"{self.key}={self.value}"


class OCMOrganizationLabel(OCMLabel):
    """
    Represents a label attached to an organization.
    """

    organization_id: str


class OCMSubscriptionLabel(OCMLabel):
    """
    Represents a label attached to a subscription.
    """

    subscription_id: str


class OCMAccountLabel(OCMLabel):
    """
    Represents a label attached to an account.
    """

    account_id: str


class LabelContainer(BaseModel):
    """
    A container for a set of labels with some convenience methods to work
    efficiently with them.
    """

    labels: dict[str, OCMLabel] = Field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.labels)

    def __bool__(self) -> bool:
        return len(self.labels) > 0

    def get(self, name: str) -> OCMLabel | None:
        return self.labels.get(name)

    def __getitem__(self, name: str) -> OCMLabel:
        return self.labels[name]

    def get_required_label(self, name: str) -> OCMLabel:
        label = self.get(name)
        if not label:
            raise ValueError(f"Required label '{name}' does not exist.")
        return label

    def get_label_value(self, name: str) -> str | None:
        label = self.get(name)
        if label:
            return label.value
        return None

    def get_values_dict(self) -> dict[str, str]:
        return {label.key: label.value for label in self.labels.values()}


class OCMServiceLogSeverity(StrEnum):
    """
    Represents the severity of a service log.
    """

    Debug = "Debug"
    Info = "Info"
    Warning = "Warning"
    Error = "Error"
    Fatal = "Fatal"


class OCMClusterServiceLogCreateModel(BaseModel):
    cluster_uuid: str
    """
    The cluster UUID is the same as external ID on the OCM cluster_mgmt API
    """

    service_name: str
    """
    The name of the service a service log entry belongs to
    """

    summary: str
    """
    Short summary of the log entry.
    """

    description: str
    """
    Detailed description of the log entry.
    """

    severity: OCMServiceLogSeverity


class OCMClusterServiceLog(OCMClusterServiceLogCreateModel):
    """
    Represents a service log entry for a cluster.
    """

    id: str
    href: str
    event_stream_id: str
    username: str

    cluster_id: str

    timestamp: datetime
    """
    The time at which the log entry was created.
    """


class OCMCapability(BaseModel):
    """
    Represents a capability (feature/feature flag) of a subscription, e.g. becoming cluster admin
    """

    name: str
    value: str


class OCMSubscriptionStatus(Enum):
    Active = "Active"
    Deprovisioned = "Deprovisioned"
    Stale = "Stale"
    Archived = "Archived"
    Reserved = "Reserved"
    Disconnected = "Disconnected"


class OCMSubscription(BaseModel):
    """
    Represents a subscription in OCM.
    """

    id: str
    href: str
    display_name: str
    created_at: datetime
    cluster_id: str

    organization_id: str
    managed: bool
    """
    A managed subscription is one that belongs to a cluster managed by OCM,
    e.g. ROSA, OSD, etc.
    """

    status: OCMSubscriptionStatus

    labels: list[OCMSubscriptionLabel] | None = None
    capabilities: list[OCMCapability] | None = None
    """
    Capabilities are a list of features/features flags that are enabled for a subscription.
    """


class OCMOrganization(BaseModel):
    """
    Represents an organization in OCM.
    """

    id: str
    name: str

    labels: list[OCMOrganizationLabel] | None = None
    capabilities: list[OCMCapability] | None = None
    """
    Capabilities are a list of features/features flags that are enabled for an organization.
    """


class ClusterDetails(BaseModel):
    ocm_cluster: OCMCluster

    organization_id: str
    capabilities: dict[str, OCMCapability]
    """
    The capabilities of a cluster. They represent feature flags and are
    found on the subscription of a cluster.
    """

    subscription_labels: LabelContainer
    organization_labels: LabelContainer

    @property
    def labels(self) -> LabelContainer:
        return build_label_container(
            self.organization_labels.labels.values(),
            self.subscription_labels.labels.values(),
        )

    def is_capability_set(self, name: str, value: str) -> bool:
        capa = self.capabilities.get(name)
        return capa is not None and capa.value == value


class OCMOIdentityProviderMappingMethod(StrEnum):
    ADD = "add"
    CLAIM = "claim"
    LOOKUP = "lookup"
    GENERATE = "generate"


class OCMOIdentityProvider(BaseModel):
    type: str
    name: str
    id: str | None = None
    href: str | None = None


class OCMOIdentityProviderGithub(OCMOIdentityProvider):
    # just basic mapping for now
    type: str = "GithubIdentityProvider"
    mapping_method: OCMOIdentityProviderMappingMethod = (
        OCMOIdentityProviderMappingMethod.ADD
    )


class OCMOIdentityProviderOidcOpenIdClaims(BaseModel):
    email: list[str]
    name: list[str]
    preferred_username: list[str]
    groups: list[str] = []

    class Config:
        frozen = True


class OCMOIdentityProviderOidcOpenId(BaseModel):
    client_id: str
    client_secret: str | None = None
    issuer: str
    claims: OCMOIdentityProviderOidcOpenIdClaims = OCMOIdentityProviderOidcOpenIdClaims(
        email=["email"],
        name=["name"],
        preferred_username=["preferred_username"],
        groups=[],
    )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OCMOIdentityProviderOidcOpenId):
            return False
        return (
            self.client_id == other.client_id
            and self.issuer == other.issuer
            and self.claims == other.claims
        )


class OCMOIdentityProviderOidc(OCMOIdentityProvider):
    type: str = "OpenIDIdentityProvider"
    mapping_method: OCMOIdentityProviderMappingMethod = (
        OCMOIdentityProviderMappingMethod.ADD
    )
    open_id: OCMOIdentityProviderOidcOpenId

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OCMOIdentityProviderOidc):
            return False
        return self.name == other.name and self.open_id == other.open_id


class OCMAddonUpgradePolicy(BaseModel):
    id: str
    addon_id: str
    cluster_id: str
    next_run: str | None
    schedule: str | None
    schedule_type: str
    version: str
    state: str | None


def build_label_container(
    *label_iterables: Iterable[OCMLabel] | None,
) -> LabelContainer:
    """
    Builds a label container from a list of labels.
    """
    merged_labels = {}
    for labels in label_iterables:
        for label in labels or []:
            merged_labels[label.key] = label
    return LabelContainer(labels=merged_labels)
