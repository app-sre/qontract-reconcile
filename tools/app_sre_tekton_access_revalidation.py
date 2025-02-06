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
from reconcile.typed_queries.tekton_pipeline_providers import (
    get_tekton_pipeline_providers,
)
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.mr.notificator import (
    CreateAppInterfaceNotificator,
    Notification,
)
from reconcile.utils.runtime.environment import init_env

EMAIL_BODY = """Hello app-interface service owner,

Access to all Tekton pipelines namespaces must be revalidated regularly. This ensures
that the access is still valid and is needed to safeguard against unauthorized access.

Please review, within one week, that all your app-interface roles that grant access to
those namespaces are assigned to the appropriate users. In order to help you identifying
those roles and users, please take a look into the app-interface documentation:
https://gitlab.cee.redhat.com/service/app-interface/-/blob/master/docs/app-sre/tekton/access-revalidation.md

If you have questions about this, please post a question in the #sd-app-sre Slack channel.

Thank you,

The AppSRE team
"""


@click.command()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option(
    "--email-dir",
    help="app-interface dir to store new AppSRE Tekton revalidation emails",
    default="data/app-interface/emails/app-sre-tekton",
)
def main(
    configfile: str,
    dry_run: bool,
    log_level: str,
    gitlab_project_id: int,
    email_dir: str,
) -> None:
    """Revalidate Glitchtip access.

    This script sends an email (via MR) to all app-interface service owners (apps)
    that have a pipelines provider associated to the application. The email asks the
    service owners to revalidate the access to the pipelines providers namespaces.
    """
    init_env(log_level=log_level, config_file=configfile)

    apps = {p.namespace.app.path for p in get_tekton_pipeline_providers()}
    notification = Notification(
        notification_type="Action Required",
        short_description="AppSRE Tekton Access Revalidation",
        description=EMAIL_BODY,
        services=list(apps),
        recipients=[],
    )
    mr = CreateAppInterfaceNotificator(
        notification,
        labels=[AUTO_MERGE],
        email_base_path=Path(email_dir),
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
