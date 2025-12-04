from collections.abc import Callable

from qontract_api.config import (
    GitHubOrgSettings,
    GitLabInstanceSettings,
    PagerDutyInstanceSettings,
    Secret,
    Settings,
    SlackIntegrationsSettings,
    SlackWorkspaceSettings,
)

from reconcile.gql_definitions.qontract_api_config.github import query as github_query
from reconcile.gql_definitions.qontract_api_config.gitlab import query as gitlab_query
from reconcile.gql_definitions.qontract_api_config.pagerduty import (
    query as pagerduty_query,
)
from reconcile.gql_definitions.qontract_api_config.slack import query as slack_query


def generate_qontract_api_config(
    query_func: Callable, default_github_org: str, default_gitlab_instance: str
) -> dict:
    """Generate qontract-api config from app-interface.

    Args:
        query_func (Callable): Function to query qontract-reconcile config.

    Returns:
        dict: Qontract-api config.
    """
    config = Settings()
    config.slack.workspaces = {
        ws.name: SlackWorkspaceSettings(
            integrations={
                integration.name: SlackIntegrationsSettings(
                    token=Secret(
                        path=integration.token.path,
                        field=integration.token.field,
                        version=integration.token.version,
                    )
                )
                for integration in ws.integrations or []
            }
        )
        for ws in slack_query(query_func).workspaces or []
    }
    config.pagerduty.instances = {
        instance.name: PagerDutyInstanceSettings(
            token=Secret(
                path=instance.token.path,
                field=instance.token.field,
                version=instance.token.version,
            )
        )
        for instance in pagerduty_query(query_func).instances or []
    }

    github_orgs = github_query(query_func).organizations or []
    config.vcs.providers.github.organizations = {
        org.url: GitHubOrgSettings(
            token=Secret(
                path=org.token.path,
                field=org.token.field,
                version=org.token.version,
            )
        )
        for org in github_orgs
    }
    gitlab_instances = gitlab_query(query_func).instances or []
    config.vcs.providers.gitlab.instances = {
        instance.url: GitLabInstanceSettings(
            token=Secret(
                path=instance.token.path,
                field=instance.token.field,
                version=instance.token.version,
            )
        )
        for instance in gitlab_instances
    }

    # add fallback token for github and gitlab
    if not (
        default_gh_org := next(
            (org for org in github_orgs if org.name == default_github_org), None
        )
    ):
        raise ValueError(
            f"Default GitHub organization '{default_github_org}' not found in app-interface."
        )
    config.vcs.providers.github.organizations["default"] = GitHubOrgSettings(
        token=Secret(
            path=default_gh_org.token.path,
            field=default_gh_org.token.field,
            version=default_gh_org.token.version,
        )
    )

    if not (
        default_gl_instance := next(
            (i for i in gitlab_instances if i.name == default_gitlab_instance), None
        )
    ):
        raise ValueError(
            f"Default GitLab instance '{default_gitlab_instance}' not found in app-interface."
        )
    config.vcs.providers.gitlab.instances["default"] = GitLabInstanceSettings(
        token=Secret(
            path=default_gl_instance.token.path,
            field=default_gl_instance.token.field,
            version=default_gl_instance.token.version,
        )
    )
    return config.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude_defaults=True
    )
