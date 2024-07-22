import logging
import sys
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel
from sretoolbox.utils import threaded

import reconcile.openshift_saas_deploy as osd
from reconcile import queries
from reconcile.gql_definitions.common.saas_files import (
    DeployResourcesV1,
    SaasResourceTemplateTargetUpstreamV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.saas_files import (
    SaasFile,
    SaasFileList,
)
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-saas-deploy-change-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class Definition(BaseModel):
    managed_resource_types: list[str]
    image_patterns: list[str]
    use_channel_in_image_tag: bool


class State(BaseModel):
    saas_file_path: str
    saas_file_name: str
    saas_file_deploy_resources: DeployResourcesV1 | None
    resource_template_name: str
    cluster: str
    namespace: str
    environment: str
    url: str
    ref: str
    parameters: dict[str, Any]
    secret_parameters: dict[str, VaultSecret]
    saas_file_definitions: Definition
    upstream: SaasResourceTemplateTargetUpstreamV1 | None
    disable: bool | None
    delete: bool | None
    target_path: str | None


def osd_run_wrapper(
    spec: tuple[str, str],
    dry_run: bool,
    available_thread_pool_size: int,
    use_jump_host: bool,
    saas_file_list: SaasFileList | None,
) -> int:
    saas_file_name, env_name = spec
    exit_code = 0
    try:
        osd.run(
            dry_run=dry_run,
            thread_pool_size=available_thread_pool_size,
            use_jump_host=use_jump_host,
            saas_file_name=saas_file_name,
            env_name=env_name,
            saas_file_list=saas_file_list,
        )
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    return exit_code


def init_gitlab(gitlab_project_id: str) -> GitLabApi:
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id, settings=settings)


def collect_state(saas_files: list[SaasFile]) -> list[State]:
    state = []
    for saas_file in saas_files:
        definitions = Definition(
            managed_resource_types=saas_file.managed_resource_types,
            image_patterns=saas_file.image_patterns,
            use_channel_in_image_tag=saas_file.use_channel_in_image_tag or False,
        )

        for resource_template in saas_file.resource_templates:
            for target in resource_template.targets:
                parameters: dict[str, Any] = {}
                parameters.update(saas_file.parameters or {})
                parameters.update(resource_template.parameters or {})
                parameters.update(target.parameters or {})
                secret_parameters: dict[str, VaultSecret] = {}
                secret_parameters.update({
                    s.name: s.secret for s in saas_file.secret_parameters or []
                })
                secret_parameters.update({
                    s.name: s.secret for s in resource_template.secret_parameters or []
                })
                secret_parameters.update({
                    s.name: s.secret for s in target.secret_parameters or []
                })
                state.append(
                    State(
                        saas_file_path=saas_file.path,
                        saas_file_name=saas_file.name,
                        saas_file_deploy_resources=saas_file.deploy_resources,
                        resource_template_name=resource_template.name,
                        cluster=target.namespace.cluster.name,
                        namespace=target.namespace.name,
                        environment=target.namespace.environment.name,
                        url=resource_template.url,
                        ref=target.ref,
                        parameters=parameters,
                        secret_parameters=secret_parameters,
                        saas_file_definitions=definitions,
                        upstream=target.upstream,
                        disable=target.disable,
                        delete=target.delete,
                        target_path=target.path,
                    )
                )
    return state


def collect_compare_diffs(
    current_state: Iterable[State],
    desired_state: Iterable[State],
    changed_paths: Iterable[str],
) -> set[str]:
    """Collect a list of URLs in a git diff format
    for each change in the merge request"""
    compare_diffs = set()
    for d in desired_state:
        # check if this diff was actually changed in the current MR
        changed_path_matches = [
            c for c in changed_paths if c.endswith(d.saas_file_path)
        ]
        if not changed_path_matches:
            # this diff was found in the graphql endpoint comparison
            # but is not a part of the changed paths.
            # the only known case for this currently is if a previous MR
            # that changes another saas file was merged but is not yet
            # reflected in the baseline graphql endpoint.
            # https://issues.redhat.com/browse/APPSRE-3029
            logging.debug(f"Diff not found in changed paths, skipping: {str(d)}")
            continue
        for c in current_state:
            if d.saas_file_name != c.saas_file_name:
                continue
            if d.resource_template_name != c.resource_template_name:
                continue
            if d.environment != c.environment:
                continue
            if d.cluster != c.cluster:
                continue
            if d.namespace != c.namespace:
                continue
            if d.ref == c.ref:
                continue
            compare_diffs.add(f"{d.url}/compare/{c.ref}...{d.ref}")

    return compare_diffs


def update_mr_with_ref_diffs(
    gitlab_project_id: str,
    gitlab_merge_request_id: int,
    current_state: Iterable[State],
    desired_state: Iterable[State],
) -> None:
    """
    Update the merge request with links to the differences in the referenced commits.
    """
    instance = queries.get_gitlab_instance()
    with GitLabApi(
        instance,
        project_id=gitlab_project_id,
        settings=queries.get_secret_reader_settings(),
    ) as gl:
        merge_request = gl.get_merge_request(gitlab_merge_request_id)
        changed_paths = gl.get_merge_request_changed_paths(merge_request)
        compare_diffs = collect_compare_diffs(
            current_state, desired_state, changed_paths
        )
        if compare_diffs:
            compare_diffs_comment_body = "Diffs:\n" + "\n".join([
                f"- {d}" for d in compare_diffs
            ])
            gl.delete_merge_request_comments(merge_request, startswith="Diffs:")
            gl.add_comment_to_merge_request(merge_request, compare_diffs_comment_body)


def run(
    dry_run: bool,
    gitlab_project_id: str,
    gitlab_merge_request_id: int,
    thread_pool_size: int,
    comparison_sha: str,
    use_jump_host: bool,
) -> None:
    comparison_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )
    # find the differences in saas-file state
    comparison_saas_file_state = collect_state(
        SaasFileList(query_func=comparison_gql_api.query).saas_files
    )
    saas_file_list = SaasFileList()
    desired_saas_file_state = collect_state(saas_file_list.saas_files)
    # compare dicts against dicts which is much faster than comparing BaseModel objects
    comparison_saas_file_state_dicts = [s.dict() for s in comparison_saas_file_state]
    saas_file_state_diffs = [
        s
        for s in desired_saas_file_state
        if s.dict() not in comparison_saas_file_state_dicts
    ]
    if not saas_file_state_diffs:
        return
    changed_saas_file_envs = {
        (d.saas_file_name, d.environment) for d in saas_file_state_diffs
    }

    update_mr_with_ref_diffs(
        gitlab_project_id,
        gitlab_merge_request_id,
        comparison_saas_file_state,
        desired_saas_file_state,
    )

    available_thread_pool_size = threaded.estimate_available_thread_pool_size(
        thread_pool_size, len(changed_saas_file_envs)
    )

    exit_codes = threaded.run(
        osd_run_wrapper,
        changed_saas_file_envs,
        thread_pool_size,
        dry_run=dry_run,
        available_thread_pool_size=available_thread_pool_size,
        use_jump_host=use_jump_host,
        saas_file_list=saas_file_list,
    )

    if [ec for ec in exit_codes if ec]:
        sys.exit(1)
