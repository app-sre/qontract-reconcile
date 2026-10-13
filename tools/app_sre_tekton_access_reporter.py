import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click
from pydantic import BaseModel, Field

from reconcile import mr_client_gateway
from reconcile.cli import (
    config_file,
    dry_run,
    gitlab_project_id,
    log_level,
)
from reconcile.gql_definitions.app_sre_tekton_access_revalidation.roles import (
    AccessV1,
    RoleV1,
)
from reconcile.gql_definitions.app_sre_tekton_access_revalidation.roles import (
    query as roles_query,
)
from reconcile.gql_definitions.fragments.membership_source import RoleMembershipSource
from reconcile.typed_queries.tekton_pipeline_providers import (
    get_tekton_pipeline_providers,
)
from reconcile.utils import gql
from reconcile.utils.membershipsources.resolver import resolve_role_members
from reconcile.utils.mr.app_sre_tekton_access_report import (
    AppSRETektonAccessReportUser,
    UpdateAppSRETektonAccessReport,
)
from reconcile.utils.runtime.environment import init_env

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

QUALIFYING_CLUSTER_ROLES = {"tekton-trigger-access", "view"}


class TektonUser(BaseModel, frozen=True):
    """Identity used for Tekton access reporting, including LDAP-only users without a file path."""

    name: str
    org_username: str
    path: str | None = None


class TektonRole(BaseModel, frozen=True):
    """Integration role with LDAP-only user support."""

    name: str
    path: str
    users: list[TektonUser]
    access: list[AccessV1] | None = None
    member_sources: list[RoleMembershipSource] | None = Field(
        None, alias="memberSources"
    )


def build_tekton_access_report_users(
    roles: list[RoleV1],
    pp_namespaces_apps: Mapping[tuple[str, str], str],
    query_func: Callable,
) -> list[AppSRETektonAccessReportUser]:
    """Resolve role membership once, then build the per-user access report."""
    resolved_roles = resolve_role_members(
        roles, user_cls=TektonUser, query_func=query_func, role_cls=TektonRole
    )

    report_users: dict[str, AppSRETektonAccessReportUser] = {}
    for r in resolved_roles:
        namespace_apps: set[str] = set()
        for a in r.access or []:
            if a.namespace is None or a.cluster_role not in QUALIFYING_CLUSTER_ROLES:
                continue
            namespace_tuple = (a.namespace.cluster.name, a.namespace.name)
            if pp_app := pp_namespaces_apps.get(namespace_tuple):
                namespace_apps.add(pp_app)

        if not namespace_apps:
            continue

        for user in r.users:
            if ru := report_users.get(user.org_username):
                for app in namespace_apps:
                    ru.add_app(app)
            else:
                report_users[user.org_username] = AppSRETektonAccessReportUser(
                    name=user.name,
                    org_username=user.org_username,
                    apps=set(namespace_apps),
                )
    return list(report_users.values())


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

    query_func = gql.get_api().query
    roles = roles_query(query_func=query_func).roles or []
    report_users = build_tekton_access_report_users(
        roles, pp_namespaces_apps, query_func
    )

    mr = UpdateAppSRETektonAccessReport(
        users=[u.generate_model() for u in report_users],
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
    main()
