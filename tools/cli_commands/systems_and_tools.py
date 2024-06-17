#!/usr/bin/env python3
# ruff: noqa: PLC0415 - `import` should be at the top-level of a file

from typing import (
    Any,
    Self,
)

from pydantic import BaseModel

from reconcile.aus.base import get_orgs_for_environment
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    DEFINITION as AUS_ORGANIZATION_DEFINITION,
)
from reconcile.gql_definitions.common.app_code_component_repos import (
    DEFINITION as CODE_COMPONENTS_DEFINITION,
)
from reconcile.gql_definitions.common.app_code_component_repos import (
    AppCodeComponentsV1,
)
from reconcile.gql_definitions.common.clusters import (
    DEFINITION as CLUSTERS_DEFINITION,
)
from reconcile.gql_definitions.common.clusters import (
    ClusterV1,
)
from reconcile.gql_definitions.common.ocm_environments import (
    DEFINITION as OCM_ENVIRONMENTS_DEFINITION,
)
from reconcile.gql_definitions.common.pagerduty_instances import (
    DEFINITION as PAGERDUTY_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.common.pagerduty_instances import (
    PagerDutyInstanceV1,
)
from reconcile.gql_definitions.common.quay_instances import (
    DEFINITION as QUAY_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.common.quay_instances import (
    QuayInstanceV1,
)
from reconcile.gql_definitions.common.slack_workspaces import (
    DEFINITION as SLACK_WORKSPACES_DEFINITION,
)
from reconcile.gql_definitions.common.slack_workspaces import (
    SlackWorkspaceV1,
)
from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DEFINITION as DYNATRACE_ENVIRONMENTS_DEFINITION,
)
from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DynatraceEnvironmentV1,
)
from reconcile.gql_definitions.fragments.aus_organization import (
    OpenShiftClusterManagerUpgradePolicyClusterV1,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.gitlab_members.gitlab_instances import (
    DEFINITION as GITLAB_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.gitlab_members.gitlab_instances import (
    GitlabInstanceV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    DEFINITION as GLITCHTIP_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    GlitchtipInstanceV1,
)
from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    DEFINITION as JENKINS_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    JenkinsInstanceV1,
)
from reconcile.gql_definitions.jira.jira_servers import (
    DEFINITION as JIRA_SERVERS_DEFINITION,
)
from reconcile.gql_definitions.jira.jira_servers import (
    JiraServerV1,
)
from reconcile.gql_definitions.statuspage.statuspages import (
    DEFINITION as STATUS_PAGES_DEFINITION,
)
from reconcile.gql_definitions.statuspage.statuspages import (
    StatusPageV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    DEFINITION as CLOUDFLARE_ACCOUNTS_DEFINITION,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    CloudflareAccountV1,
)
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    DEFINITION as AWS_ACCOUNTS_DEFINITION,
)
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    DEFINITION as UNLEASH_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    UnleashInstanceV1,
)
from reconcile.gql_definitions.vault_instances.vault_instances import (
    DEFINITION as VAULT_INSTANCES_DEFINITION,
)
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultInstanceV1,
)
from reconcile.statuspage.integration import get_status_pages
from reconcile.typed_queries.cloudflare import get_cloudflare_accounts
from reconcile.typed_queries.clusters import get_clusters
from reconcile.typed_queries.dynatrace import get_dynatrace_environments
from reconcile.typed_queries.gitlab_instances import (
    get_gitlab_instances,
)
from reconcile.typed_queries.glitchtip import get_glitchtip_instances
from reconcile.typed_queries.jenkins import get_jenkins_instances
from reconcile.typed_queries.jira import get_jira_servers
from reconcile.typed_queries.ocm import get_ocm_environments
from reconcile.typed_queries.pagerduty_instances import get_pagerduty_instances
from reconcile.typed_queries.quay import get_quay_instances
from reconcile.typed_queries.repos import get_code_components
from reconcile.typed_queries.slack import get_slack_workspaces
from reconcile.typed_queries.terraform_tgw_attachments.aws_accounts import (
    get_aws_accounts,
)
from reconcile.typed_queries.unleash import get_unleash_instances
from reconcile.typed_queries.vault import get_vault_instances
from reconcile.utils import (
    gql,
)


class SystemTool(BaseModel):
    system_type: str
    system_id: str
    name: str
    url: str
    description: str
    enumeration: str

    @classmethod
    def init_from_model(
        cls, model: Any, enumeration: Any, parent: str | None = None
    ) -> Self:
        match model:
            case GitlabInstanceV1():
                return cls.init_from_gitlab(model, enumeration)
            case JenkinsInstanceV1():
                return cls.init_from_jenkins(model, enumeration)
            case ClusterV1():
                return cls.init_from_cluster(model, enumeration)
            case AWSAccountV1():
                return cls.init_from_aws_account(model, enumeration)
            case DynatraceEnvironmentV1():
                return cls.init_from_dynatrace_environment(model, enumeration)
            case GlitchtipInstanceV1():
                return cls.init_from_glitchtip_instance(model, enumeration)
            case JiraServerV1():
                return cls.init_from_jira_server(model, enumeration)
            case OCMEnvironment():
                return cls.init_from_ocm_environment(model, enumeration)
            case OpenShiftClusterManagerUpgradePolicyClusterV1():
                return cls.init_from_ocm_org_upgrade_policy_cluster(
                    model, enumeration, parent
                )
            case PagerDutyInstanceV1():
                return cls.init_from_pagerduty_instance(model, enumeration)
            case QuayInstanceV1():
                return cls.init_from_quay_instance(model, enumeration)
            case SlackWorkspaceV1():
                return cls.init_from_slack_workspace(model, enumeration)
            case StatusPageV1():
                return cls.init_from_status_page(model, enumeration)
            case UnleashInstanceV1():
                return cls.init_from_unleash_instance(model, enumeration)
            case VaultInstanceV1():
                return cls.init_from_vault_instance(model, enumeration)
            case CloudflareAccountV1():
                return cls.init_from_cloudflare_account(model, enumeration)
            case AppCodeComponentsV1():
                return cls.init_from_code_component(model, enumeration)
            case _:
                raise NotImplementedError(f"unsupported: {model}")

    @classmethod
    def init_from_gitlab(cls, g: GitlabInstanceV1, enumeration: Any) -> Self:
        return cls(
            system_type="gitlab",
            system_id=g.name,
            name=g.name,
            url=g.url,
            description=g.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_jenkins(cls, j: JenkinsInstanceV1, enumeration: Any) -> Self:
        return cls(
            system_type="jenkins",
            system_id=j.name,
            name=j.name,
            url=j.server_url,
            description=j.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_cluster(cls, c: ClusterV1, enumeration: Any) -> Self:
        return cls(
            system_type="openshift",
            system_id=c.spec.q_id if c.spec else "",
            name=c.name,
            url=c.server_url,
            description=c.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_aws_account(cls, a: AWSAccountV1, enumeration: Any) -> Self:
        return cls(
            system_type="aws",
            system_id=a.uid,
            name=a.name,
            url=a.console_url,
            description=a.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_dynatrace_environment(
        cls, dt: DynatraceEnvironmentV1, enumeration: Any
    ) -> Self:
        return cls(
            system_type="dynatrace",
            system_id=dt.environment_id,
            name=dt.name,
            url=dt.environment_url,
            description=dt.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_glitchtip_instance(
        cls, g: GlitchtipInstanceV1, enumeration: Any
    ) -> Self:
        return cls(
            system_type="glitchtip",
            system_id=g.name,
            name=g.name,
            url=g.console_url,
            description=g.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_jira_server(cls, j: JiraServerV1, enumeration: Any) -> Self:
        return cls(
            system_type="jira",
            system_id=j.name,
            name=j.name,
            url=j.server_url,
            description=j.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_ocm_environment(cls, o: OCMEnvironment, enumeration: Any) -> Self:
        return cls(
            system_type="ocm",
            system_id=o.name,
            name=o.name,
            url=o.url,
            description=o.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_ocm_org_upgrade_policy_cluster(
        cls,
        c: OpenShiftClusterManagerUpgradePolicyClusterV1,
        enumeration: Any,
        parent: str | None = None,
    ) -> Self:
        return cls(
            system_type="openshift",
            system_id=c.spec.q_id if c.spec else "",
            name=c.name,
            url=c.server_url,
            description=f"cluster {c.name} in organization {parent}"
            if parent
            else c.name,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_pagerduty_instance(
        cls, p: PagerDutyInstanceV1, enumeration: Any
    ) -> Self:
        return cls(
            system_type="pagerduty",
            system_id=p.name,
            name=p.name,
            url=p.description,  # no url
            description=p.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_quay_instance(cls, q: QuayInstanceV1, enumeration: Any) -> Self:
        return cls(
            system_type="quay",
            system_id=q.name,
            name=q.name,
            url=f"https://{q.name}.pagerduty.com",
            description=q.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_slack_workspace(cls, s: SlackWorkspaceV1, enumeration: Any) -> Self:
        return cls(
            system_type="slack",
            system_id=s.name,
            name=s.name,
            url=f"https://{s.name}.slack.com",
            description=s.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_status_page(cls, s: StatusPageV1, enumeration: Any) -> Self:
        return cls(
            system_type="statuspage",
            system_id=s.name,
            name=s.name,
            url=s.url,
            description=s.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_unleash_instance(cls, u: UnleashInstanceV1, enumeration: Any) -> Self:
        return cls(
            system_type="unleash",
            system_id=u.name,
            name=u.name,
            url=u.url,
            description=u.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_vault_instance(cls, v: VaultInstanceV1, enumeration: Any) -> Self:
        return cls(
            system_type="vault",
            system_id=v.name,
            name=v.name,
            url=v.address,
            description=v.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_cloudflare_account(
        cls, a: CloudflareAccountV1, enumeration: Any
    ) -> Self:
        return cls(
            system_type="cloudflare",
            system_id=a.name,
            name=a.name,
            url="https://dash.cloudflare.com/",
            description=a.description,
            enumeration=enumeration,
        )

    @classmethod
    def init_from_code_component(cls, c: AppCodeComponentsV1, enumeration: Any) -> Self:
        return cls(
            system_type=c.resource,
            system_id=c.name,
            name=c.name,
            url=c.url,
            description=c.description or "",
            enumeration=enumeration,
        )


class SystemToolInventory:
    def __init__(self) -> None:
        self.systems_and_tools: list[SystemTool] = []

    def append(self, model: Any, enumeration: Any, parent: str | None = None) -> None:
        self.systems_and_tools.append(
            SystemTool.init_from_model(model, enumeration, parent=parent)
        )

    def update(
        self, models: list[Any], enumeration: Any, parent: str | None = None
    ) -> None:
        for m in models:
            self.append(m, enumeration, parent=parent)

    @property
    def data(self) -> list[dict[str, Any]]:
        return [
            {
                "type": st.system_type,
                "id": st.system_id,
                "name": st.name,
                "url": st.url,
                "description": st.description.replace("\n", "\\n"),
                "enumeration": st.enumeration.strip().replace("\n", ",")
                if st.enumeration
                else "",
            }
            for st in self.systems_and_tools
        ]

    @property
    def columns(self) -> list[str]:
        return [
            "type",
            "id",
            "name",
            "url",
            "description",
            "enumeration",
        ]


def get_systems_and_tools_inventory() -> SystemToolInventory:
    gql_api = gql.get_api()
    inventory = SystemToolInventory()

    inventory.update(get_gitlab_instances(), GITLAB_INSTANCES_DEFINITION)
    inventory.update(get_jenkins_instances(), JENKINS_INSTANCES_DEFINITION)
    inventory.update(get_clusters(), CLUSTERS_DEFINITION)
    inventory.update(get_aws_accounts(gql_api), AWS_ACCOUNTS_DEFINITION)
    inventory.update(get_dynatrace_environments(), DYNATRACE_ENVIRONMENTS_DEFINITION)
    inventory.update(get_glitchtip_instances(), GLITCHTIP_INSTANCES_DEFINITION)
    inventory.update(get_jira_servers(), JIRA_SERVERS_DEFINITION)
    ocm_environments = get_ocm_environments()
    inventory.update(ocm_environments, OCM_ENVIRONMENTS_DEFINITION)
    for ocm_env in ocm_environments:
        ocm_env_orgs = get_orgs_for_environment(
            "", ocm_env.name, query_func=gql_api.query
        )
        for ocm_org in ocm_env_orgs:
            if ocm_org.labels and "systems_and_tools_report" in ocm_org.labels:
                inventory.update(
                    ocm_org.upgrade_policy_clusters or [],
                    AUS_ORGANIZATION_DEFINITION,
                    parent=f"{ocm_org.name} ({ocm_env.name})",
                )

    inventory.update(
        get_pagerduty_instances(gql_api.query), PAGERDUTY_INSTANCES_DEFINITION
    )
    inventory.update(get_quay_instances(), QUAY_INSTANCES_DEFINITION)
    inventory.update(get_slack_workspaces(), SLACK_WORKSPACES_DEFINITION)
    inventory.update(get_status_pages(), STATUS_PAGES_DEFINITION)
    inventory.update(get_unleash_instances(), UNLEASH_INSTANCES_DEFINITION)
    inventory.update(get_vault_instances(), VAULT_INSTANCES_DEFINITION)
    inventory.update(get_cloudflare_accounts(), CLOUDFLARE_ACCOUNTS_DEFINITION)
    inventory.update(
        [
            c
            for c in get_code_components()
            if c.resource in {"gitops", "infrastructure"}
        ],
        CODE_COMPONENTS_DEFINITION,
    )

    inventory.systems_and_tools.append(
        SystemTool(
            system_type="github",
            system_id="github",
            name="github",
            url="https://github.com",
            description="github",
            enumeration="github",
        )
    )

    return inventory
