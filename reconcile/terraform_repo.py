import logging
from collections.abc import (
    Mapping,
    MutableMapping,
)
from typing import (
    Any,
    Callable,
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


class AWSAuthSecret(BaseModel):
    path: str
    version: Optional[int]


class AWSAccount(BaseModel):
    name: str
    uid: str
    secret: AWSAuthSecret


class TFRepo(BaseModel):
    """This is what the integration outputs and is input for the executor to perform terraform operations"""

    name: str
    repository: str
    ref: str
    project_path: str
    account: AWSAccount
    delete: Optional[bool]


class ActionPlan(BaseModel):
    dry_run: bool
    repos: list[TFRepo]


def get_repos(query_func: Callable) -> list[TFRepo]:
    """Return all terraform repos defined in app-interface"""
    query_results = query(query_func=query_func).repos
    if query_results:
        return [gql_to_tf_repo(repo) for repo in query_results]
    return []


def get_existing_state(state: State) -> list[TFRepo]:
    """Get the existing state of terraform repos from S3"""
    repo_list: list[TFRepo] = []
    keys = state.ls()
    for key in keys:
        value = state.get(key.lstrip("/"), None)
        repo = TFRepo.parse_raw(value)

        if repo is not None:
            repo_list.append(repo)

    return repo_list


def map_repos(repos: list[TFRepo]) -> MutableMapping[str, TFRepo]:
    """Generate keys for each repo to more easily compare"""
    repo_map: MutableMapping[str, TFRepo] = dict()
    for repo in repos:
        # repo names are unique per app interface instance as enforced in the schema
        repo_map[repo.name] = repo

    return repo_map


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
            retrieved_path = gl.get_file("{}/config.tf".format(path), ref)

            if not retrieved_path:
                raise ParameterError(
                    'No config.tf found in path: "{}" on repo: "{}". Ensure that a config.tf file is present in this path.'.format(
                        path, repo_url
                    )
                )
        except (KeyError, AttributeError):
            raise ParameterError(
                'Invalid ref: "{}" on repo: "{}"'.format(ref, repo_url)
            )


def diff_missing(
    a: Mapping[str, TFRepo],
    b: Mapping[str, TFRepo],
    requireDelete: bool = False,
) -> MutableMapping[str, TFRepo]:
    """
    Returns a mapping of repos that are present in mapping a but missing in mapping b
    When requireDelete = True, each repo from a is checked to ensure that the delete flag is set"""
    missing: MutableMapping[str, TFRepo] = dict()
    for a_key, a_repo in a.items():
        b_repo = b.get(a_key)
        if b_repo is None:
            if requireDelete is True and a_repo.delete is not True:
                raise ParameterError(
                    'To delete the terraform repo "{}", you must set delete: true in the repo definition'.format(
                        a_repo.name
                    )
                )
            check_ref(a_repo.repository, a_repo.ref, a_repo.project_path)
            missing[a_key] = a_repo

    return missing


def diff_changed(
    a: Mapping[str, TFRepo], b: Mapping[str, TFRepo]
) -> MutableMapping[str, TFRepo]:
    """
    Returns a mapping of repos that have changed between a and b in the form of returning their b values
    In order for Terraform to work as expected, the tenant can only update the ref between MRs
    Updating account, repo, or project_path can lead to unexpected behavior so we error
    on that
    """
    changed: MutableMapping[str, TFRepo] = dict()
    for a_key, a_repo in a.items():
        b_repo = b.get(a_key, a_repo)
        if (
            a_repo.account != b_repo.account
            or a_repo.name != b_repo.name
            or a_repo.project_path != b_repo.project_path
            or a_repo.repository != b_repo.repository
        ):
            raise ParameterError(
                'Only the `ref` and `delete` parameters for a terraform repo may be updated in merge requests on repo: "{}"'.format(
                    a_repo.name
                )
            )
        if (a_repo.ref != b_repo.ref) or (a_repo.delete != b_repo.delete):
            check_ref(b_repo.repository, b_repo.ref, b_repo.project_path)
            changed[a_key] = b_repo

    return changed


def gql_to_tf_repo(repo: TerraformRepoV1) -> TFRepo:
    """
    Converts the GQL/state representation of a Terraform repo to a
    TFRepo class that can be more easily marshalled/unmarshalled from state file
    """
    return TFRepo(
        name=repo.name,
        repository=repo.repository,
        ref=repo.ref,
        project_path=repo.project_path,
        account=AWSAccount(
            name=repo.account.name,
            uid=repo.account.uid,
            secret=AWSAuthSecret(
                path=repo.account.automation_token.path,
                version=repo.account.automation_token.version,
            ),
        ),
        delete=repo.delete,
    )


def merge_results(
    created: Mapping[str, TFRepo], updated: Mapping[str, TFRepo]
) -> list[TFRepo]:
    """
    Merges results into a RepoOutput dict which will be transformed to outputted YAML.
    This includes checking modified values for a delete flag
    """
    output: list[TFRepo] = []
    for c_value in created.values():
        logging.info(["create_repo", c_value.account.name, c_value.name])
        output.append(c_value)
    for u_value in updated.values():
        if u_value.delete is True:
            logging.info(["delete_repo", u_value.account.name, u_value.name])
            output.append(u_value)
        else:
            logging.info(["update_repo", u_value.account.name, u_value.name])
            output.append(u_value)
    return output


def update_state(
    created: Mapping[str, TFRepo],
    deleted: Mapping[str, TFRepo],
    updated: Mapping[str, TFRepo],
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
            if cu_val.delete is True:
                state.rm(cu_key)
            else:
                state.add(cu_key, cu_val.json(), True)
        for d_key in deleted.keys():
            state.rm(d_key)
    except KeyError:
        pass


def calculate_diff(
    existing_state: list[TFRepo],
    desired_state: list[TFRepo],
    dry_run: bool,
    state: State,
) -> list[TFRepo]:
    """Diffs existing and desired state as well as updates the state in S3 if this is not a dry-run operation"""
    existing_map = map_repos(existing_state)
    desired_map = map_repos(desired_state)

    to_be_created = diff_missing(desired_map, existing_map)
    to_be_updated = diff_changed(existing_map, desired_map)

    # indicates repos which have had their definitions deleted from App Interface
    # a pre-requisite to this step is setting the delete flag in the repo definition
    to_be_deleted = diff_missing(existing_map, desired_map, True)

    if not dry_run:
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

    action_plan = ActionPlan(
        dry_run=dry_run, repos=calculate_diff(existing, desired, dry_run, state)
    )

    if print_to_file:
        try:
            with open(print_to_file, "w") as output_file:
                yaml.safe_dump(
                    data=action_plan.dict(), stream=output_file, explicit_start=True
                )
        except FileNotFoundError:
            raise ParameterError(
                "Unable to write to specified 'print_to_file' location: {}".format(
                    print_to_file
                )
            )
    else:
        print(yaml.safe_dump(data=action_plan.dict(), explicit_start=True))


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {"repos": get_repos(query_func=gqlapi.query)}
