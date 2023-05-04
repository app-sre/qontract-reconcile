import logging
from collections.abc import Callable
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
from reconcile.utils.differ import (
    DiffResult,
    diff_iterables,
)
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
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


class TerraformRepoIntegrationParams(PydanticRunParams):
    print_to_file: Optional[str]
    validate_git: bool


class TerraformRepoIntegration(
    QontractReconcileIntegration[TerraformRepoIntegrationParams]
):
    def __init__(self, params: TerraformRepoIntegrationParams) -> None:
        super().__init__(params)
        self.qontract_integration = "terraform_repo"
        self.qontract_integration_version = make_semver(0, 1, 0)
        self.qontract_tf_prefix = "qrtfrepo"

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Optional[Callable] = None,
    ) -> None:

        gqlapi = gql.get_api()

        state = init_state(integration=QONTRACT_INTEGRATION)
        if defer:
            defer(state.cleanup)

        desired = self.get_repos(query_func=gqlapi.query)
        existing = self.get_existing_state(state)

        repo_diff = self.calculate_diff(existing, desired, dry_run, state)

        action_plan = ActionPlan(dry_run=dry_run, repos=repo_diff)

        if self.params.print_to_file:
            try:
                with open(self.params.print_to_file, "w") as output_file:
                    yaml.safe_dump(
                        data=action_plan.dict(), stream=output_file, explicit_start=True
                    )
            except FileNotFoundError:
                raise ParameterError(
                    f"Unable to write to specified 'print_to_file' location: {self.params.print_to_file}"
                )
        else:
            print(yaml.safe_dump(data=action_plan.dict(), explicit_start=True))

    def get_repos(self, query_func: Callable) -> list[TerraformRepoV1]:
        """Return all terraform repos defined in app-interface"""
        query_results = query(query_func=query_func).repos
        if query_results:
            return query_results
        return []

    def get_existing_state(self, state: State) -> list[TerraformRepoV1]:
        """Get the existing state of terraform repos from S3"""
        repo_list: list[TerraformRepoV1] = []
        keys = state.ls()
        for key in keys:
            if value := state.get(key.lstrip("/"), None):
                repo = TerraformRepoV1.parse_raw(value)

                if repo is not None:
                    repo_list.append(repo)

        return repo_list

    def check_ref(self, repo_url: str, ref: str) -> None:
        """
        Checks whether a Git ref is valid
        """
        instance = queries.get_gitlab_instance()
        with GitLabApi(
            instance,
            settings=queries.get_secret_reader_settings(),
            project_url=repo_url,
        ) as gl:
            try:
                gl.get_commit_sha(ref=ref, repo_url=repo_url)
            except (KeyError, AttributeError):
                raise ParameterError(f'Invalid ref: "{ref}" on repo: "{repo_url}"')

    def merge_results(
        self,
        diff: DiffResult[TerraformRepoV1, TerraformRepoV1, str],
    ) -> list[TerraformRepoV1]:
        """
        Merges results into a RepoOutput dict which will be transformed to outputted YAML.
        This includes checking modified values for a delete flag
        """
        output: list[TerraformRepoV1] = []
        for add_key, add_val in diff.add.items():
            logging.info(["create_repo", add_val.account.name, add_key])
            output.append(add_val)
        for change_key, change_val in diff.change.items():
            if change_val.desired.delete:
                logging.info(
                    ["delete_repo", change_val.desired.account.name, change_key]
                )
                output.append(change_val.desired)
            else:
                logging.info(
                    ["update_repo", change_val.desired.account.name, change_key]
                )
                output.append(change_val.desired)
        return output

    def update_state(
        self,
        diff: DiffResult[TerraformRepoV1, TerraformRepoV1, str],
        state: State,
    ) -> None:
        """
        State is represented as a JSON dump of TerraformRepoV1 data structures
        In regards to deleting a Terraform Repo, when the delete flag is set to True, then
        the state representation of this repo is also deleted even though the definition will
        still exist in App Interface
        """
        try:
            for add_key, add_val in diff.add.items():
                state.add(add_key, add_val.json(by_alias=True), force=True)
            for delete_key in diff.delete.keys():
                state.rm(delete_key)
            for change_key, change_val in diff.change.items():
                if change_val.desired.delete:
                    state.rm(change_key)
                else:
                    state.add(
                        change_key, change_val.desired.json(by_alias=True), force=True
                    )
        except KeyError:
            pass

    def calculate_diff(
        self,
        existing_state: list[TerraformRepoV1],
        desired_state: list[TerraformRepoV1],
        dry_run: bool,
        state: Optional[State],
    ) -> list[TerraformRepoV1]:
        """Diffs existing and desired state as well as updates the state in S3 if this is not a dry-run operation"""
        diff = diff_iterables(existing_state, desired_state, lambda x: x.name)

        if self.params.validate_git:
            # added repos: do standard validation that SHA is valid
            for add_repo in diff.add.values():
                self.check_ref(add_repo.repository, add_repo.ref)
        # removed repos: ensure that delete = true already
        for delete_repo in diff.delete.values():
            if not delete_repo.delete:
                raise ParameterError(
                    f'To delete the terraform repo "{delete_repo.name}", you must set delete: true in the repo definition'
                )
        # changed repos: ensure that params are updated appropriately
        for changes in diff.change.values():
            c = changes.current
            d = changes.desired
            if (
                c.account != d.account
                or c.name != d.name
                or c.project_path != d.project_path
                or c.repository != d.repository
            ):
                raise ParameterError(
                    f'Only the `ref` and `delete` parameters for a terraform repo may be updated in merge requests on repo: "{d.name}"'
                )
            if self.params.validate_git:
                self.check_ref(d.repository, d.ref)

        if not dry_run and state:
            self.update_state(diff, state)

        return self.merge_results(diff)

    def early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        gqlapi = gql.get_api()
        return {
            "repos": [repo.dict() for repo in self.get_repos(query_func=gqlapi.query)]
        }
