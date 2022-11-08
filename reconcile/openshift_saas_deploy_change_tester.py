import sys
import json
import copy
import logging
from typing import Any

from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils import gql
import reconcile.openshift_saas_deploy as osd

from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "openshift-saas-deploy-change-tester"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def osd_run_wrapper(
    spec, dry_run, available_thread_pool_size, use_jump_host, gitlab_project_id
):
    saas_file_name, env_name = spec
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
        exit_code = e.code if isinstance(e.code, int) else 1
    return exit_code


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id, settings=settings)


def collect_state(saas_files: list[dict[str, Any]]):
    state = []
    for saas_file in saas_files:
        saas_file_path = saas_file["path"]
        saas_file_name = saas_file["name"]
        saas_file_deploy_resources = saas_file.get("deployResources")
        saas_file_parameters = json.loads(saas_file.get("parameters") or "{}")
        saas_file_secret_parameters = saas_file.get("secretParameters") or []
        saas_file_definitions = {
            "managed_resource_types": saas_file["managedResourceTypes"],
            "image_patterns": saas_file["imagePatterns"],
            "use_channel_in_image_tag": saas_file.get("use_channel_in_image_tag")
            or False,
        }
        resource_templates = saas_file["resourceTemplates"]
        for resource_template in resource_templates:
            resource_template_name = resource_template["name"]
            resource_template_parameters = json.loads(
                resource_template.get("parameters") or "{}"
            )
            resource_template_secret_parameters = (
                resource_template.get("secretParameters") or []
            )
            resource_template_url = resource_template["url"]
            for target in resource_template["targets"]:
                namespace_info = target["namespace"]
                namespace = namespace_info["name"]
                cluster = namespace_info["cluster"]["name"]
                environment = namespace_info["environment"]["name"]
                target_ref = target["ref"]
                target_upstream = target.get("upstream")
                target_disable = target.get("disable")
                target_delete = target.get("delete")
                target_parameters = json.loads(target.get("parameters") or "{}")
                target_secret_parameters = target.get("secretParameters") or []
                parameters = {}
                parameters.update(saas_file_parameters)
                parameters.update(resource_template_parameters)
                parameters.update(target_parameters)
                secret_parameters = {}
                secret_parameters.update(
                    {
                        s.get("name"): s.get("secret")
                        for s in saas_file_secret_parameters
                    }
                )
                secret_parameters.update(
                    {
                        s.get("name"): s.get("secret")
                        for s in resource_template_secret_parameters
                    }
                )
                secret_parameters.update(
                    {s.get("name"): s.get("secret") for s in target_secret_parameters}
                )
                state.append(
                    {
                        "saas_file_path": saas_file_path,
                        "saas_file_name": saas_file_name,
                        "saas_file_deploy_resources": saas_file_deploy_resources,
                        "resource_template_name": resource_template_name,
                        "cluster": cluster,
                        "namespace": namespace,
                        "environment": environment,
                        "url": resource_template_url,
                        "ref": target_ref,
                        "parameters": parameters,
                        "secret_parameters": secret_parameters,
                        "saas_file_definitions": copy.deepcopy(saas_file_definitions),
                        "upstream": target_upstream,
                        "disable": target_disable,
                        "delete": target_delete,
                        "target_path": target.get("path"),
                    }
                )
    return state


def collect_compare_diffs(current_state, desired_state, changed_paths):
    """Collect a list of URLs in a git diff format
    for each change in the merge request"""
    compare_diffs = set()
    for d in desired_state:
        # check if this diff was actually changed in the current MR
        changed_path_matches = [
            c for c in changed_paths if c.endswith(d["saas_file_path"])
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
            if d["saas_file_name"] != c["saas_file_name"]:
                continue
            if d["resource_template_name"] != c["resource_template_name"]:
                continue
            if d["environment"] != c["environment"]:
                continue
            if d["cluster"] != c["cluster"]:
                continue
            if d["namespace"] != c["namespace"]:
                continue
            if d["ref"] == c["ref"]:
                continue
            compare_diffs.add(f"{d['url']}/compare/{c['ref']}...{d['ref']}")

    return compare_diffs


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
    comparison_saas_file_state = collect_state(
        queries.get_saas_files(gqlapi=comparison_gql_api)
    )
    desired_saas_file_state = collect_state(
        queries.get_saas_files(gqlapi=gql.get_api())
    )
    saas_file_state_diffs = [
        s for s in desired_saas_file_state if s not in comparison_saas_file_state
    ]
    if not saas_file_state_diffs:
        return
    changed_saas_file_envs = {
        (d["saas_file_name"], d["environment"]) for d in saas_file_state_diffs
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
        gitlab_project_id=gitlab_project_id,
    )

    if [ec for ec in exit_codes if ec]:
        sys.exit(1)
