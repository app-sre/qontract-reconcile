import logging
from collections import defaultdict
from pathlib import Path

import click

from reconcile import mr_client_gateway
from reconcile.cli import (
    config_file,
    dry_run,
    gitlab_project_id,
    log_level,
)
from reconcile.gql_definitions.app_sre_tekton_access_revalidation.users import (
    query as users_query,
)
from reconcile.typed_queries.tekton_pipeline_providers import (
    get_tekton_pipeline_providers,
)
from reconcile.utils import gql
from reconcile.utils.mr.app_sre_tekton_access_report import (
    AppSRETektonAccessReportUser,
    UpdateAppSRETektonAccessReport,
)
from reconcile.utils.runtime.environment import init_env


@click.command()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option(
    "--workbook-path",
    help="path to AppSRE Tekton access revalidation workbook markdown file",
    default="docs/app-sre/tekton/access-revalidation-workbook.md",
)
def main(
    configfile: str,
    dry_run: bool,
    log_level: str,
    gitlab_project_id: int,
    workbook_path: str,
) -> None:
    """Update AppSRE Tekton access report.

    This script updates the AppSRE Tekton access report (markdown file) with the latest
    access information.
    """

    init_env(log_level=log_level, config_file=configfile)

    # pipeline providers namespaces dict, containing the all the pipelines namespaces
    # the (cluster_name, namespace_name) tuple to app_name correspondence.
    pp_namespaces_apps = {
        (p.namespace.cluster.name, p.namespace.name): p.namespace.app.name
        for p in get_tekton_pipeline_providers()
    }

    report_users: dict[str, AppSRETektonAccessReportUser] = {}
    users = users_query(query_func=gql.get_api().query).users or []
    for u in users:
        namespace_roles = defaultdict(set)
        for r in u.roles or []:
            if r.access is None:
                continue

            for a in r.access:
                if a.namespace is None:
                    continue

                namespace_tuple = (a.namespace.cluster.name, a.namespace.name)
                namespace_roles[namespace_tuple].add(a.role)

        for namespace_tuple, roles in namespace_roles.items():
            if pp_app := pp_namespaces_apps.get(namespace_tuple):
                if "tekton-trigger-access" in roles or "view" in roles:
                    if ru := report_users.get(u.org_username):
                        ru.add_app(pp_app)
                    else:
                        report_users[u.org_username] = AppSRETektonAccessReportUser(
                            name=u.name, org_username=u.org_username, apps={pp_app}
                        )

    mr = UpdateAppSRETektonAccessReport(
        users=[u.generate_model() for u in report_users.values()],
        workbook_path=Path(workbook_path),
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
