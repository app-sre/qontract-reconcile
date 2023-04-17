import logging
from audioop import add
from typing import (
    Callable,
    Mapping,
    Optional,
)

import yaml
from deepdiff import DeepHash
from pydantic import BaseModel

from reconcile import queries
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    TerraformRepoV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "terraform-repo"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)


class AWSAuthToken(BaseModel):
    path: str
    field: str
    version: Optional[int]


class AWSAccount(BaseModel):
    name: str
    uid: str
    token: AWSAuthToken


class RepoOutput(BaseModel):
    """This is what the integration outputs and is input for the executor to perform terraform operations"""

    name: str
    git: str
    ref: str
    project_path: str
    account: AWSAccount
    dry_run: bool
    destroy: bool


def get_repos(query_func: Callable) -> list[TerraformRepoV1]:
    """Return all terraform repos defined in app-interface"""
    return query(query_func=query_func).repos or []


def get_existing_state(state: State) -> list[TerraformRepoV1]:
    """Get the existing state of terraform repos from S3"""
    repo_list: list[TerraformRepoV1] = list()
    keys = state.ls()
    for key in keys:
        value = state.get(key, None)
        if not value == None:
            repo_list.append(value)

    return repo_list


def map_repos(repos: list[TerraformRepoV1]) -> Mapping[str, TerraformRepoV1]:
    """Generate keys for each repo to more easily compare"""
    repo_map: Mapping[str, TerraformRepoV1] = dict()
    for repo in repos:
        key = "{}_{}".format(repo.account.uid, repo.name)
        repo_map[key] = repo

    return repo_map


def diff_missing(
    a: Mapping[str, TerraformRepoV1], b: Mapping[str, TerraformRepoV1]
) -> Mapping[str, TerraformRepoV1]:
    """Returns a mapping of repos that are present in mapping a but missing in mapping b"""
    missing: Mapping[str, TerraformRepoV1] = dict()
    for a_key, a_repo in a.items():
        b_repo = b.get(a_key)
        if b_repo is None:
            missing[a_key] = a_repo

    return missing


def diff_changed(
    a: Mapping[str, TerraformRepoV1], b: Mapping[str, TerraformRepoV1]
) -> Mapping[str, TerraformRepoV1]:
    """Returns a mapping of repos that have changed between a and b in the form of returning their b values"""
    changed: Mapping[str, TerraformRepoV1] = dict()
    for a_key, a_repo in a.items():
        b_repo = b.get(a_key, a_repo)
        if not DeepHash(a_repo) == DeepHash(b_repo):
            changed[a_key] = b_repo

    return changed


def repo_action_plan(repo: TerraformRepoV1, dry_run: bool, destroy: bool) -> RepoOutput:
    """Converts the GQL/state representation of a Terraform repo to an action plan that the executor will act on"""
    return RepoOutput(
        name=repo.name,
        git=repo.repository,
        ref=repo.ref,
        project_path=repo.project_path,
        account=AWSAccount(
            name=repo.account.name,
            uid=repo.account.uid,
            token=AWSAuthToken(
                path=repo.account.automation_token.path,
                field=repo.account.automation_token.field,
                version=repo.account.automation_token.version,
            ),
        ),
        dry_run=dry_run,
        destroy=destroy,
    )


def merge_results(
    created: Mapping[str, TerraformRepoV1],
    deleted: Mapping[str, TerraformRepoV1],
    updated: Mapping[str, TerraformRepoV1],
    dry_run: bool,
) -> list[RepoOutput]:
    """Merges results into a RepoOutput dict which will be transformed to outputted YAML"""
    output: list[RepoOutput] = list()
    for c_value in created.values():
        logging.info(["create_repo", c_value.account.name, c_value.name])
        output.append(repo_action_plan(c_value, dry_run, False))
    for d_value in deleted.values():
        logging.info(["delete_repo", d_value.account.name, d_value.name])
        output.append(repo_action_plan(d_value, dry_run, True))
    for u_value in updated.values():
        logging.info(["update_repo", u_value.account.name, u_value.name])
        output.append(repo_action_plan(u_value, dry_run, False))
    return output


def update_state(
    created: Mapping[str, TerraformRepoV1],
    deleted: Mapping[str, TerraformRepoV1],
    updated: Mapping[str, TerraformRepoV1],
    state: State,
):
    """State represents TerraformRepoV1 data structures equivalent to their GQL representations"""
    created_and_updated = created | updated
    for cu_key, cu_val in created_and_updated.items():
        state.add(cu_key, cu_val, True)
    for d_key in deleted.keys():
        state.rm(d_key)


def diff(
    existing_state: list[TerraformRepoV1],
    desired_state: list[TerraformRepoV1],
    dry_run: bool,
    state: State,
) -> list[RepoOutput]:
    """Diffs existing and desired state as well as updates the state in S3 if this is not a dry-run operation"""
    existing_map = map_repos(existing_state)
    desired_map = map_repos(desired_state)

    to_be_created = diff_missing(existing_map, desired_map, dry_run)
    to_be_deleted = diff_missing(desired_map, existing_map, dry_run)
    to_be_updated = diff_changed(existing_map, desired_map, dry_run)

    if not dry_run:
        update_state(to_be_created, to_be_deleted, to_be_updated, state)

    return merge_results(to_be_created, to_be_deleted, to_be_updated)


@defer
def run(
    dry_run: bool = True,
    print_to_file: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:

    gqlapi = gql.get_api()

    state = init_state(integration=QONTRACT_INTEGRATION)
    defer(state.cleanup)

    # taking inspiration from slack_usergroups.py
    desired = get_repos(query_func=gqlapi.query)
    existing = get_existing_state(state)

    action_plan = diff(existing, desired, dry_run, state)

    if print_to_file:
        try:
            with open(print_to_file, "w") as output_file:
                yaml.safe_dump(action_plan, output_file)
        except FileNotFoundError:
            raise ParameterError(
                "Unable to write to specified 'print_to_file' location: {}".format(
                    print_to_file
                )
            )
    else:
        print(yaml.safe_dump(action_plan))
