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
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.mr.notificator import (
    CreateAppInterfaceNotificator,
    Notification,
)
from reconcile.utils.runtime.environment import init_env

EMAIL_BODY = """Hello App-Interface service owner,

Access to all Glitchtip organizations and projects must be revalidated regularly.
This ensures that the access is still valid and is needed to safeguard against unauthorized access.
Please review, within one week, all your App-Interface roles referencing Glitchtip
organizations (https://gitlab.cee.redhat.com/search?search=glitchtip_roles%3A&nav_source=navbar&project_id=13582&group_id=5301&search_code=true&repository_ref=master).

If you have questions about this, please post a question in the #sd-app-sre Slack channel.

Thank you,
The SRE team
"""


@click.command()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option(
    "--glitchtip-access-revalidation-email-path",
    help="App-interface path to store new Glitchtip revalidation emails",
    default="data/app-interface/emails/glitchtip",
)
def main(
    configfile: str,
    dry_run: bool,
    log_level: str,
    gitlab_project_id: int,
    glitchtip_access_revalidation_email_path: str,
) -> None:
    """Revalidate Glitchtip access.

    This script sends an email (via MR) to all App-Interface service owners (apps)
    referencing Glitchtip projects. The email asks the service owners to
    revalidate Glitchtip access for their projects.
    """
    init_env(log_level=log_level, config_file=configfile)

    glitchtip_projects = (
        glitchtip_project_query(query_func=gql.get_api().query).glitchtip_projects or []
    )

    apps = {project.app.path for project in glitchtip_projects if project.app}

    notification = Notification(
        notification_type="Action Required",
        short_description="Glitchtip Access Revalidation",
        description=EMAIL_BODY,
        services=list(apps),
        recipients=[],
    )
    mr = CreateAppInterfaceNotificator(
        notification,
        labels=[AUTO_MERGE],
        email_base_path=Path(glitchtip_access_revalidation_email_path),
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
