from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from sretoolbox.utils import threaded

import reconcile.openshift_saas_deploy as osd
from reconcile import queries
from reconcile.typed_queries.saas_files import (
    SaasFileList,
)
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saas_diff import (
    State,
    collect_state,
    find_ref_diffs,
)
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from collections.abc import Iterable

QONTRACT_INTEGRATION = "openshift-saas-deploy-change-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def osd_run_wrapper(
    spec: tuple[str, str],
    dry_run: bool,
    available_thread_pool_size: int,
    saas_file_list: SaasFileList | None,
) -> int:
    saas_file_name, env_name = spec
    exit_code = 0
    try:
        osd.run(
            dry_run=dry_run,
            thread_pool_size=available_thread_pool_size,
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


def collect_compare_diffs(
    current_state: Iterable[State],
    desired_state: Iterable[State],
    changed_paths: Iterable[str],
) -> set[str]:
    """Collect a list of URLs in a git diff format
    for each change in the merge request"""
    return {
        f"{d.url}/compare/{c.ref}...{d.ref}"
        for d, c in find_ref_diffs(current_state, desired_state, changed_paths)
    }


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
    comparison_saas_file_state_dicts = [
        s.model_dump() for s in comparison_saas_file_state
    ]
    saas_file_state_diffs = [
        s
        for s in desired_saas_file_state
        if s.model_dump() not in comparison_saas_file_state_dicts
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
        saas_file_list=saas_file_list,
    )

    if [ec for ec in exit_codes if ec]:
        sys.exit(1)
