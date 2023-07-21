import logging
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

import yaml
from pydantic import (
    BaseModel,
    ValidationError,
)

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


class RepoSecret(BaseModel):
    path: str
    version: Optional[int]


class RepoOutput(BaseModel):
    repository: str
    name: str
    ref: str
    project_path: str
    delete: bool
    secret: RepoSecret


class OutputFile(BaseModel):
    """
    Output of the QR terraform-repo integration and input to the executor
    which removes some information that is unnecessary for the executor to parse
    """

    dry_run: bool
    repos: list[RepoOutput]


class TerraformRepoIntegrationParams(PydanticRunParams):
    output_file: Optional[str]
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

        state = init_state(integration=self.name)
        if defer:
            defer(state.cleanup)

        desired = self.get_repos(query_func=gqlapi.query)
        existing = self.get_existing_state(state)

        repo_diff_result = self.calculate_diff(
            existing_state=existing, desired_state=desired, dry_run=dry_run, state=state
        )

        if repo_diff_result:
            # put together output to pass to executor
            actions_list: list[RepoOutput] = []

            for repo in repo_diff_result:
                actions_list.append(
                    RepoOutput(
                        repository=repo.repository,
                        name=repo.name,
                        ref=repo.ref,
                        project_path=repo.project_path,
                        delete=repo.delete or False,
                        secret=RepoSecret(
                            path=repo.account.automation_token.path,
                            version=repo.account.automation_token.version,
                        ),
                    )
                )

            output = OutputFile(dry_run=dry_run, repos=actions_list)

            if self.params.output_file:
                try:
                    with open(self.params.output_file, "w") as output_file:
                        yaml.safe_dump(
                            data=output.dict(),
                            stream=output_file,
                            explicit_start=True,
                        )
                except FileNotFoundError:
                    raise ParameterError(
                        f"Unable to write to '{self.params.output_file}'"
                    )
            else:
                print(yaml.safe_dump(data=output.dict(), explicit_start=True))

    def get_repos(self, query_func: Callable) -> list[TerraformRepoV1]:
        """Gets a list of terraform repos defined in App Interface

        :param query_func: function which queries GQL server
        :type query_func: Callable
        :return: list of Terraform repos or empty list if none are defined in A-I
        :rtype: list[TerraformRepoV1]
        """
        query_results = query(query_func=query_func).repos
        if query_results:
            return query_results
        return []

    def get_existing_state(self, state: State) -> list[TerraformRepoV1]:
        """Gets the state of terraform infrastructure currently deployed (stored in S3)

        :param state: S3 state class to retrieve from
        :type state: State
        :return: list of terraform repos or empty list if state is unparsable or no repos are deployed
        :rtype: list[TerraformRepoV1]
        """
        repo_list: list[TerraformRepoV1] = []
        keys = state.ls()
        for key in keys:
            if value := state.get(key.lstrip("/"), None):
                try:
                    repo = TerraformRepoV1.parse_obj(value)
                    repo_list.append(repo)
                except ValidationError as err:
                    logging.error(
                        f"{err}\nUnable to parse existing state for repo: '{key}', skipping"
                    )

        return repo_list

    def check_ref(self, repo_url: str, ref: str) -> None:
        """Validates that a Git SHA exists

        :param repo_url: full project URL including https/http
        :type repo_url: str
        :param ref: git SHA
        :type ref: str
        :raises ParameterError: if the Git ref is invalid or project is not reachable
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
                raise ParameterError(
                    f'Invalid ref: "{ref}" on repo: "{repo_url}". Or the project repo is not reachable'
                )

    def merge_results(
        self,
        diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str],
    ) -> list[TerraformRepoV1]:
        """Transforms the diff or repos into a list of repos that need to be changed or deleted

        :param diff_result: diff result of existing and desired state
        :type diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str]
        :return: list of repos that need to be changed or deleted
        :rtype: list[TerraformRepoV1]
        """
        output: list[TerraformRepoV1] = []
        for add_key, add_val in diff_result.add.items():
            logging.info(["create_repo", add_val.account.name, add_key])
            output.append(add_val)
        for change_key, change_val in diff_result.change.items():
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
        diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str],
        state: State,
    ) -> None:
        """The state of deployed terraform infrastructure is tracked using AWS S3.
        Each repo is saved as a JSON dump of a TerraformRepoV1 object meaning that it can
        be easily compared against the GQL representation in App Interface

        :param diff_result: diff of existing and desired state
        :type diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str]
        :param state: S3 state class
        :type state: State
        """
        try:
            for add_key, add_val in diff_result.add.items():
                # state.add already performs a json.dumps(key) so we export the
                # pydantic model as a dict to avoid a double json dump with extra quotes
                state.add(add_key, add_val.dict(by_alias=True), force=True)
            for delete_key in diff_result.delete.keys():
                state.rm(delete_key)
            for change_key, change_val in diff_result.change.items():
                if change_val.desired.delete:
                    state.rm(change_key)
                else:
                    state.add(
                        change_key, change_val.desired.dict(by_alias=True), force=True
                    )
        except KeyError:
            pass

    def calculate_diff(
        self,
        existing_state: list[TerraformRepoV1],
        desired_state: list[TerraformRepoV1],
        dry_run: bool,
        state: Optional[State],
    ) -> Optional[list[TerraformRepoV1]]:
        """Calculated the difference between existing and desired state
        to determine what actions the executor will need to take

        :param existing_state: list of Terraform infrastructure that is currently applied
        :type existing_state: list[TerraformRepoV1]
        :param desired_state: list of Terraform infrastructure we want
        :type desired_state: list[TerraformRepoV1]
        :param dry_run: determines whether State should be updated
        :type dry_run: bool
        :param state: AWS S3 state
        :type state: Optional[State]
        :raises ParameterError: if there is an invalid operation performed like trying to delete
        a representation in A-I before setting the delete flag
        :return: the terraform repo to act on
        :rtype: TerraformRepoV1
        """
        diff = diff_iterables(existing_state, desired_state, lambda x: x.name)

        merged = self.merge_results(diff)

        # validate that only one repo is being modified in each MR
        # this lets us fail early and avoid multiple GL requests we don't need to make
        if dry_run and len(merged) > 1:
            raise Exception(
                "Only one repository can be modified per merge request, please split your change out into multiple MRs. Hint: try rebasing your merge request"
            )

        # added repos: do standard validation that SHA is valid
        if self.params.validate_git:
            for add_repo in diff.add.values():
                self.check_ref(add_repo.repository, add_repo.ref)
        # removed repos: ensure that delete = true already
        for delete_repo in diff.delete.values():
            if not delete_repo.delete:
                raise ParameterError(
                    f'To delete the terraform repo "{delete_repo.name}", you must set delete: true in the repo definition'
                )
        # changed repos: prevent non deterministic terraform behavior by disabling updating key parameters
        # also do SHA verification
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

        if len(merged) != 0:
            if not dry_run and state:
                self.update_state(diff, state)
            return merged
        return None

    def early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        gqlapi = gql.get_api()
        return {
            "repos": [repo.dict() for repo in self.get_repos(query_func=gqlapi.query)]
        }
