import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

from reconcile import mr_client_gateway
from reconcile.cli import (
    config_file,
    dry_run,
    gitlab_project_id,
    log_level,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    GlitchtipProjectV1,
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.glitchtip.models import Organization
from reconcile.utils.membershipsources.resolver import resolve_role_members
from reconcile.utils.mr.glitchtip_access_reporter import (
    GlitchtipAccessReportOrg,
    GlitchtipAccessReportUser,
    UpdateGlitchtipAccessReport,
)
from reconcile.utils.runtime.environment import init_env

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_MEMBER_ROLE = "member"


def get_user_role(organization: Organization, roles: RoleV1) -> str:
    for role in roles.glitchtip_roles or []:
        if role.organization.name == organization.name:
            return role.role
    return DEFAULT_MEMBER_ROLE


def build_glitchtip_access_report_users(
    glitchtip_projects: list[GlitchtipProjectV1],
    query_func: Callable,
) -> list[GlitchtipAccessReportUser]:
    """Resolve role membership once, then build the per-user access report."""
    roles = [
        role
        for project in glitchtip_projects
        for team in project.teams
        for role in team.roles
    ]
    resolved_roles = resolve_role_members(roles, user_cls=UserV1, query_func=query_func)
    resolved_iter = iter(resolved_roles)

    users: dict[str, GlitchtipAccessReportUser] = {}
    for project in glitchtip_projects:
        org = Organization(name=project.organization.name)
        for team in project.teams:
            for _role in team.roles:
                resolved_role = next(resolved_iter)
                for user in resolved_role.users:
                    report_user = users.setdefault(
                        user.org_username,
                        GlitchtipAccessReportUser(
                            name=user.name, username=user.org_username, organizations=[]
                        ),
                    )
                    if org.name not in [
                        org_.name for org_ in report_user.organizations
                    ]:
                        report_user.organizations.append(
                            GlitchtipAccessReportOrg(
                                name=org.name,
                                access_level=get_user_role(org, resolved_role),
                            )
                        )
    return list(users.values())


@click.command()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option(
    "--glitchtip-access-revalidation-workbook-path",
    help="path to glitchtip access revalidation workbook markdown file",
    default="docs/app-sre/platform-services/glitchtip/access_revalidation_workbook.md",
)
def main(
    configfile: str,
    dry_run: bool,
    log_level: str,
    gitlab_project_id: int,
    glitchtip_access_revalidation_workbook_path: str,
) -> None:
    """Update Glitchtip access report.

    This script updates the Glitchtip access report (markdown file) with the latest
    access information.
    """

    init_env(log_level=log_level, config_file=configfile)

    query_func = gql.get_api().query
    glitchtip_projects = (
        glitchtip_project_query(query_func=query_func).glitchtip_projects or []
    )
    users = build_glitchtip_access_report_users(glitchtip_projects, query_func)

    mr = UpdateGlitchtipAccessReport(
        users=users,
        workbook_path=Path(glitchtip_access_revalidation_workbook_path),
        dry_run=dry_run,
    )
    with mr_client_gateway.init(
        gitlab_project_id=gitlab_project_id, sqs_or_gitlab="gitlab"
    ) as mr_cli:
        result = mr.submit(cli=mr_cli)
        if result:
            logging.info(["created_mr", result.web_url])


if __name__ == "__main__":
    main()
