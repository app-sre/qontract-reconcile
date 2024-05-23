#!/usr/bin/env python3
# ruff: noqa: PLC0415 - `import` should be at the top-level of a file

from typing import (
    Any,
    Self,
    cast,
)

from pydantic import BaseModel

from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.gql_definitions.common.pagerduty_instances import (
    PagerDutyInstanceV1,
)
from reconcile.gql_definitions.common.quay_instances import QuayInstanceV1
from reconcile.gql_definitions.common.slack_workspaces import SlackWorkspaceV1
from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DynatraceEnvironmentV1,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.gitlab_members.gitlab_instances import GitlabInstanceV1
from reconcile.gql_definitions.glitchtip.glitchtip_instance import GlitchtipInstanceV1
from reconcile.gql_definitions.jenkins_configs.jenkins_instances import (
    JenkinsInstanceV1,
)
from reconcile.gql_definitions.jira.jira_servers import JiraServerV1
from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    UnleashInstanceV1,
)
from reconcile.gql_definitions.vault_instances.vault_instances import VaultInstanceV1
from reconcile.statuspage.integration import get_status_pages
from reconcile.typed_queries.clusters import get_clusters
from reconcile.typed_queries.dynatrace import get_dynatrace_environments
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.glitchtip import get_glitchtip_instances
from reconcile.typed_queries.jenkins import get_jenkins_instances
from reconcile.typed_queries.jira import get_jira_servers
from reconcile.typed_queries.ocm import get_ocm_environments
from reconcile.typed_queries.pagerduty_instances import get_pagerduty_instances
from reconcile.typed_queries.quay import get_quay_instances
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

    @classmethod
    def init_from_model(cls, model: Any) -> Self:
        match model:
            case GitlabInstanceV1():
                return cls.init_from_gitlab(cast(GitlabInstanceV1, model))
            case JenkinsInstanceV1():
                return cls.init_from_jenkins(cast(JenkinsInstanceV1, model))
            case ClusterV1():
                return cls.init_from_cluster(cast(ClusterV1, model))
            case AWSAccountV1():
                return cls.init_from_aws_account(cast(AWSAccountV1, model))
            case DynatraceEnvironmentV1():
                return cls.init_from_dynatrace_environment(
                    cast(DynatraceEnvironmentV1, model)
                )
            case GlitchtipInstanceV1():
                return cls.init_from_glitchtip_instance(
                    cast(GlitchtipInstanceV1, model)
                )
            case JiraServerV1():
                return cls.init_from_jira_server(cast(JiraServerV1, model))
            case OCMEnvironment():
                return cls.init_from_ocm_environment(cast(OCMEnvironment, model))
            case PagerDutyInstanceV1():
                return cls.init_from_pagerduty_instance(
                    cast(PagerDutyInstanceV1, model)
                )
            case QuayInstanceV1():
                return cls.init_from_quay_instance(cast(QuayInstanceV1, model))
            case SlackWorkspaceV1():
                return cls.init_from_slack_workspace(cast(SlackWorkspaceV1, model))
            case StatusPageV1():
                return cls.init_from_status_page(cast(StatusPageV1, model))
            case UnleashInstanceV1():
                return cls.init_from_unleash_instance(cast(UnleashInstanceV1, model))
            case VaultInstanceV1():
                return cls.init_from_vault_instance(cast(VaultInstanceV1, model))
            case _:
                raise NotImplementedError(f"unsupported: {model}")

    @classmethod
    def init_from_gitlab(cls, g: GitlabInstanceV1) -> Self:
        return cls(
            system_type="gitlab",
            system_id=g.name,
            name=g.name,
            url=g.url,
            description=g.description,
        )

    @classmethod
    def init_from_jenkins(cls, j: JenkinsInstanceV1) -> Self:
        return cls(
            system_type="jenkins",
            system_id=j.name,
            name=j.name,
            url=j.server_url,
            description=j.description,
        )

    @classmethod
    def init_from_cluster(cls, c: ClusterV1) -> Self:
        return cls(
            system_type="openshift",
            system_id=c.spec.q_id if c.spec else "",
            name=c.name,
            url=c.server_url,
            description=c.description,
        )

    @classmethod
    def init_from_aws_account(cls, a: AWSAccountV1) -> Self:
        return cls(
            system_type="aws",
            system_id=a.uid,
            name=a.name,
            url=a.console_url,
            description=a.description,
        )

    @classmethod
    def init_from_dynatrace_environment(cls, dt: DynatraceEnvironmentV1) -> Self:
        return cls(
            system_type="dynatrace",
            system_id=dt.environment_id,
            name=dt.name,
            url=dt.environment_url,
            description=dt.description,
        )

    @classmethod
    def init_from_glitchtip_instance(cls, g: GlitchtipInstanceV1) -> Self:
        return cls(
            system_type="glitchtip",
            system_id=g.name,
            name=g.name,
            url=g.console_url,
            description=g.description,
        )

    @classmethod
    def init_from_jira_server(cls, j: JiraServerV1) -> Self:
        return cls(
            system_type="jira",
            system_id=j.name,
            name=j.name,
            url=j.server_url,
            description=j.description,
        )

    @classmethod
    def init_from_ocm_environment(cls, o: OCMEnvironment) -> Self:
        return cls(
            system_type="ocm",
            system_id=o.name,
            name=o.name,
            url=o.url,
            description=o.description,
        )

    @classmethod
    def init_from_pagerduty_instance(cls, p: PagerDutyInstanceV1) -> Self:
        return cls(
            system_type="pagerduty",
            system_id=p.name,
            name=p.name,
            url=p.description,  # no url
            description=p.description,
        )

    @classmethod
    def init_from_quay_instance(cls, q: QuayInstanceV1) -> Self:
        return cls(
            system_type="quay",
            system_id=q.name,
            name=q.name,
            url=f"https://{q.name}.pagerduty.com",
            description=q.description,
        )

    @classmethod
    def init_from_slack_workspace(cls, s: SlackWorkspaceV1) -> Self:
        return cls(
            system_type="slack",
            system_id=s.name,
            name=s.name,
            url=f"https://{s.name}.slack.com",
            description=s.description,
        )

    @classmethod
    def init_from_status_page(cls, s: StatusPageV1) -> Self:
        return cls(
            system_type="statuspage",
            system_id=s.name,
            name=s.name,
            url=s.url,
            description=s.description,
        )

    @classmethod
    def init_from_unleash_instance(cls, u: UnleashInstanceV1) -> Self:
        return cls(
            system_type="unleash",
            system_id=u.name,
            name=u.name,
            url=u.url,
            description=u.description,
        )

    @classmethod
    def init_from_vault_instance(cls, v: VaultInstanceV1) -> Self:
        return cls(
            system_type="vault",
            system_id=v.name,
            name=v.name,
            url=v.address,
            description=v.description,
        )


class SystemToolInventory:
    def __init__(self) -> None:
        self.systems_and_tools: list[SystemTool] = []

    def append(self, model: Any) -> None:
        self.systems_and_tools.append(SystemTool.init_from_model(model))

    def update(self, models: list[Any]) -> None:
        for m in models:
            self.append(m)

    @property
    def data(self) -> list[dict[str, Any]]:
        return [
            {
                "type": st.system_type,
                "id": st.system_id,
                "name": st.name,
                "url": st.url,
                "description": st.description.replace("\n", "\\n"),
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
        ]


def get_systems_and_tools_inventory() -> SystemToolInventory:
    gql_api = gql.get_api()
    inventory = SystemToolInventory()

    inventory.update(get_gitlab_instances())
    inventory.update(get_jenkins_instances())
    inventory.update(get_clusters())
    inventory.update(get_aws_accounts(gql_api))
    inventory.update(get_dynatrace_environments())
    inventory.update(get_glitchtip_instances())
    inventory.update(get_jira_servers())
    inventory.update(get_ocm_environments())
    inventory.update(get_pagerduty_instances(gql_api.query))
    inventory.update(get_quay_instances())
    inventory.update(get_slack_workspaces())
    inventory.update(get_status_pages())
    inventory.update(get_unleash_instances())
    inventory.update(get_vault_instances())

    inventory.systems_and_tools.append(
        SystemTool(
            system_type="github",
            system_id="github",
            name="github",
            url="https://github.com",
            description="github",
        )
    )

    return inventory
