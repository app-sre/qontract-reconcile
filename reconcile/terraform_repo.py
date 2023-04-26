import logging
from collections.abc import Mapping, MutableMapping, Callable
from typing import (
    Any,
    Optional,
)

import yaml
from pydantic import BaseModel

from reconcile import queries
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    TerraformRepoV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "terraform-repo"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)


class ActionPlan(BaseModel):
    dry_run: bool
    repos: list[TerraformRepoV1]


def get_repos(query_func: Callable) -> list[TerraformRepoV1]:
    """Return all terraform repos defined in app-interface"""
    query_results = query(query_func=query_func).repos
    if query_results:
        return query_results
    return []


def get_existing_state(state: State) -> list[TerraformRepoV1]:
    """Get the existing state of terraform repos from S3"""
    repo_list: list[TerraformRepoV1] = []
    keys = state.ls()
    for key in keys:
        if value := state.get(key.lstrip("/"), None):
            repo = TerraformRepoV1.parse_raw(value)

            if repo is not None:
                repo_list.append(repo)

    return repo_list


def map_repos(repos: list[TerraformRepoV1]) -> MutableMapping[str, TerraformRepoV1]:
    """Generate keys for each repo to more easily compare"""
    return {repo.name: repo for repo in repos}


def check_ref(repo_url: str, ref: str, path: str) -> None:
    """
    Checks whether a Git ref is valid
    and whether config.tf exists in the project path"""
    instance = queries.get_gitlab_instance()
    with GitLabApi(
        instance, settings=queries.get_secret_reader_settings(), project_url=repo_url
    ) as gl:
        try:
            gl.get_commit_sha(ref=ref, repo_url=repo_url)
            retrieved_path = gl.get_file(f"{path}/config.tf", ref)

            if not retrieved_path:
                raise ParameterError(
                    f'No config.tf found in path: "{path}" on repo: "{repo_url}". Ensure that a config.tf file is present in this path.'
                )
        except (KeyError, AttributeError):
            raise ParameterError(f'Invalid ref: "{ref}" on repo: "{repo_url}"')


def diff_missing(
    a: Mapping[str, TerraformRepoV1],
    b: Mapping[str, TerraformRepoV1],
    require_delete: bool = False,
) -> MutableMapping[str, TerraformRepoV1]:
    """
    Returns a mapping of repos that are present in mapping a but missing in mapping b
    When requireDelete = True, each repo from a is checked to ensure that the delete flag is set"""
    missing: MutableMapping[str, TerraformRepoV1] = dict()
    for a_key, a_repo in a.items():
        if a_key not in b:
            if require_delete and not a_repo.delete:
                raise ParameterError(
                    f'To delete the terraform repo "{a_repo.name}", you must set delete: true in the repo definition'
                )
            missing[a_key] = a_repo

    return missing


def diff_changed(
    a: Mapping[str, TerraformRepoV1], b: Mapping[str, TerraformRepoV1]
) -> MutableMapping[str, TerraformRepoV1]:
    """
    Returns a mapping of repos that have changed between a and b in the form of returning their b values
    In order for Terraform to work as expected, the tenant can only update the ref between MRs
    Updating account, repo, or project_path can lead to unexpected behavior so we error
    on that
    """
    changed: MutableMapping[str, TerraformRepoV1] = dict()
    for a_key, a_repo in a.items():
        b_repo = b.get(a_key, a_repo)
        if (
            a_repo.account != b_repo.account
            or a_repo.name != b_repo.name
            or a_repo.project_path != b_repo.project_path
            or a_repo.repository != b_repo.repository
        ):
            raise ParameterError(
                f'Only the `ref` and `delete` parameters for a terraform repo may be updated in merge requests on repo: "{a_repo.name}"'
            )
        if (a_repo.ref != b_repo.ref) or (a_repo.delete != b_repo.delete):
            changed[a_key] = b_repo

    return changed


def merge_results(
    created: Mapping[str, TerraformRepoV1], updated: Mapping[str, TerraformRepoV1]
) -> list[TerraformRepoV1]:
    """
    Merges results into a RepoOutput dict which will be transformed to outputted YAML.
    This includes checking modified values for a delete flag
    """
    output: list[TerraformRepoV1] = []
    for c_value in created.values():
        logging.info(["create_repo", c_value.account.name, c_value.name])
        output.append(c_value)
    for u_value in updated.values():
        if u_value.delete:
            logging.info(["delete_repo", u_value.account.name, u_value.name])
            output.append(u_value)
        else:
            logging.info(["update_repo", u_value.account.name, u_value.name])
            output.append(u_value)
    return output


def update_state(
    created: Mapping[str, TerraformRepoV1],
    deleted: Mapping[str, TerraformRepoV1],
    updated: Mapping[str, TerraformRepoV1],
    state: State,
) -> None:
    """
    State represents TFRepo data structures similar to their GQL representations.
    In regards to deleting a Terraform Repo, when the delete flag is set to True, then
    the state representation of this repo is also deleted even though the definition may
    still exist in App Interface
    """
    created_and_updated = {**created, **updated}
    try:
        for cu_key, cu_val in created_and_updated.items():
            if cu_val.delete:
                state.rm(cu_key)
            else:
                state.add(cu_key, cu_val.json(by_alias=True), True)
        for d_key in deleted.keys():
            state.rm(d_key)
    except KeyError:
        pass


def calculate_diff(
    existing_state: list[TerraformRepoV1],
    desired_state: list[TerraformRepoV1],
    dry_run: bool,
    state: Optional[State],
) -> list[TerraformRepoV1]:
    """Diffs existing and desired state as well as updates the state in S3 if this is not a dry-run operation"""
    existing_map = map_repos(existing_state)
    desired_map = map_repos(desired_state)

    to_be_created = diff_missing(desired_map, existing_map)
    to_be_updated = diff_changed(existing_map, desired_map)

    # indicates repos which have had their definitions deleted from App Interface
    # a pre-requisite to this step is setting the delete flag in the repo definition
    to_be_deleted = diff_missing(existing_map, desired_map, True)

    if not dry_run and state:
        update_state(to_be_created, to_be_deleted, to_be_updated, state)

    return merge_results(to_be_created, to_be_updated)


@defer
def run(
    dry_run: bool = True,
    print_to_file: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:

    gqlapi = gql.get_api()

    state = init_state(integration=QONTRACT_INTEGRATION)
    if defer:
        defer(state.cleanup)

    desired = get_repos(query_func=gqlapi.query)
    existing = get_existing_state(state)

    repo_diff = calculate_diff(existing, desired, dry_run, state)

    # validate that each new/updated repo is pointing to a valid git ref and
    # has config.tf in the project path
    for repo in repo_diff:
        if not repo.delete:
            check_ref(repo.repository, repo.ref, repo.project_path)

    action_plan = ActionPlan(dry_run=dry_run, repos=repo_diff)

    if print_to_file:
        try:
            with open(print_to_file, "w") as output_file:
                yaml.safe_dump(
                    data=action_plan.dict(), stream=output_file, explicit_start=True
                )
        except FileNotFoundError:
            raise ParameterError(
                f"Unable to write to specified 'print_to_file' location: {print_to_file}"
            )
    else:
        print(yaml.safe_dump(data=action_plan.dict(), explicit_start=True))


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {"repos": [repo.dict() for repo in get_repos(query_func=gqlapi.query)]}
