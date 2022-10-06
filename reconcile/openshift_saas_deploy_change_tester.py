import sys

from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils import gql
import reconcile.openshift_saas_deploy as osd
from reconcile.saas_file_owners import collect_state, collect_compare_diffs

from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "openshift-saas-deploy-change-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def osd_run_wrapper(
    diff, dry_run, available_thread_pool_size, use_jump_host, gitlab_project_id
):
    saas_file_name = diff["saas_file_name"]
    env_name = diff["environment"]
    exit_code = 0
    try:
        osd.run(
            dry_run=dry_run,
            thread_pool_size=available_thread_pool_size,
            use_jump_host=use_jump_host,
            saas_file_name=saas_file_name,
            env_name=env_name,
            gitlab_project_id=gitlab_project_id,
        )
    except SystemExit as e:
        exit_code = e.code
    return exit_code


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id, settings=settings)


def update_mr_with_ref_diffs(
    gitlab_project_id, gitlab_merge_request_id, current_state, desired_state
):
    """
    Update the merge request with links to the differences in the referenced commits.
    """
    instance = queries.get_gitlab_instance()
    gl = GitLabApi(
        instance,
        project_id=gitlab_project_id,
        settings=queries.get_secret_reader_settings(),
    )
    changed_paths = gl.get_merge_request_changed_paths(gitlab_merge_request_id)
    compare_diffs = collect_compare_diffs(current_state, desired_state, changed_paths)
    if compare_diffs:
        compare_diffs_comment_body = "Diffs:\n" + "\n".join(
            [f"- {d}" for d in compare_diffs]
        )
        gl.add_comment_to_merge_request(
            gitlab_merge_request_id, compare_diffs_comment_body
        )


def run(
    dry_run: bool,
    gitlab_project_id: str,
    gitlab_merge_request_id: str,
    thread_pool_size: int,
    comparison_sha: str,
    use_jump_host: bool,
):
    comparison_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )

    # find the differences in saas-file state
    comparison_saas_file_state = collect_state(comparison_gql_api)
    desired_saas_file_state = collect_state(gql.get_api())
    saas_file_state_diffs = [
        s for s in desired_saas_file_state if s not in comparison_saas_file_state
    ]
    if not saas_file_state_diffs:
        return

    update_mr_with_ref_diffs(
        gitlab_project_id,
        gitlab_merge_request_id,
        comparison_saas_file_state,
        desired_saas_file_state,
    )

    available_thread_pool_size = threaded.estimate_available_thread_pool_size(
        thread_pool_size, len(saas_file_state_diffs)
    )

    exit_codes = threaded.run(
        osd_run_wrapper,
        saas_file_state_diffs,
        thread_pool_size,
        dry_run=dry_run,
        available_thread_pool_size=available_thread_pool_size,
        use_jump_host=use_jump_host,
        gitlab_project_id=gitlab_project_id,
    )

    if [ec for ec in exit_codes if ec]:
        sys.exit(1)
