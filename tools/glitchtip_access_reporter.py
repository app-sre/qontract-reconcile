import logging
from pathlib import Path

import click

from reconcile import mr_client_gateway
from reconcile.cli import (
    config_file,
    dry_run,
    gitlab_project_id,
    log_level,
)
from reconcile.glitchtip.integration import get_user_role
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.glitchtip.models import Organization
from reconcile.utils.mr.glitchtip_access_reporter import (
    GlitchtipAccessReportOrg,
    GlitchtipAccessReportUser,
    UpdateGlitchtipAccessReport,
)
from reconcile.utils.runtime.environment import init_env


@click.command()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option(
    "--glitchtip-access-revalidation-workbook-path",
    help="path to glitchtip access revalidation workbook markdown file",
    default="docs/glitchtip/access_revalidation_workbook.md",
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

    glitchtip_projects = (
        glitchtip_project_query(query_func=gql.get_api().query).glitchtip_projects or []
    )

    users: dict[str, GlitchtipAccessReportUser] = {}
    for project in glitchtip_projects:
        org = Organization(name=project.organization.name)
        for team in project.teams:
            for role in team.roles:
                for user in role.users:
                    report_user = users.setdefault(
                        user.org_username,
                        GlitchtipAccessReportUser(
                            name=user.name, username=user.org_username, organizations=[]
                        ),
                    )
                    if org.name not in [
                        _org.name for _org in report_user.organizations
                    ]:
                        report_user.organizations.append(
                            GlitchtipAccessReportOrg(
                                name=org.name,
                                access_level=get_user_role(org, role),
                            )
                        )

    mr = UpdateGlitchtipAccessReport(
        users=list(users.values()),
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
    main()  # pylint: disable=no-value-for-parameter
