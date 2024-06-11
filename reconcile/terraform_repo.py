import logging
from collections.abc import Callable
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ValidationError,
)

from reconcile import queries
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    TerraformRepoV1,
    TerraformRepoVariablesV1,
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


class RepoOutput(BaseModel):
    repository: str
    name: str
    ref: str
    project_path: str
    delete: bool
    aws_creds: VaultSecret
    variables: TerraformRepoVariablesV1 | None
    bucket: str | None
    region: str | None
    bucket_path: str | None
    require_fips: bool
    tf_version: str


class OutputFile(BaseModel):
    """
    Output of the QR terraform-repo integration and input to the executor
    which removes some information that is unnecessary for the executor to parse
    """

    dry_run: bool
    repos: list[RepoOutput]


class TerraformRepoIntegrationParams(PydanticRunParams):
    output_file: str | None
    validate_git: bool
    gitlab_project_id: str | None
    gitlab_merge_request_id: int | None


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
        defer: Callable | None = None,
    ) -> None:
        gqlapi = gql.get_api()

        state = init_state(integration=self.name)
        if defer:
            defer(state.cleanup)

        desired = self.get_repos(query_func=gqlapi.query)
        try:
            existing = self.get_existing_state(state)

            repo_diff_result = self.calculate_diff(
                existing_state=existing,
                desired_state=desired,
                dry_run=dry_run,
                state=state,
                recreate_state=False,
            )

            if repo_diff_result:
                self.print_output(repo_diff_result, dry_run)
        except ValidationError as err:
            # when updating TerraformRepoV1 GQL schema, Pydantic does not gracefully handle these changes and fails to parse
            # the existing state stored in S3. This is due to a behavior in Pydantic V1 that has since been addressed in V2
            # https://docs.pydantic.dev/latest/blog/pydantic-v2/#required-vs-nullable-cleanup
            logging.error(err)
            logging.info(
                "Unable to parse existing Terraform-Repo state from S3. Note that this is separate from the actual .tfstate files. Terraform Repo will re-create its own state upon merge and will not update any infrastructure. This typically occurs with changes to the Terraform Repo schema files and is normally resolved once state is re-created."
            )
            repo_diff_result = self.calculate_diff(
                existing_state=[],
                desired_state=desired,
                dry_run=dry_run,
                state=state,
                recreate_state=True,
            )

            if repo_diff_result:
                self.print_output(repo_diff_result, dry_run)

    def print_output(self, diff: list[TerraformRepoV1], dry_run: bool) -> OutputFile:
        """Parses and prints the output of a Terraform Repo diff for the executor

        :param diff: list of terraform repos to be acted on
        :type diff: list[TerraformRepoV1]
        :param dry_run: whether the executor should perform a tf apply
        :type dry_run: bool

        :return: output of diff (used for testing)
        :rtype: OutputFile
        """
        actions_list: list[RepoOutput] = []

        for repo in diff:
            out_repo = RepoOutput(
                repository=repo.repository,
                name=repo.name,
                ref=repo.ref,
                project_path=repo.project_path,
                delete=repo.delete or False,
                require_fips=repo.require_fips or False,
                tf_version=repo.tf_version,
                aws_creds=repo.account.automation_token,
                variables=repo.variables,
            )
            # terraform-repo will store its statefiles in a specified directory if there is a
            # terraform-state yaml file associated with the AWS account and a configuration is
            # listed for terraform-repo, otherwise it will default to loading this information
            # from the automation_token secret in Vault
            if repo.account.terraform_state:
                for integration in repo.account.terraform_state.integrations:
                    if integration.integration == "terraform-repo":
                        out_repo.bucket = repo.account.terraform_state.bucket
                        out_repo.region = repo.account.terraform_state.region
                        out_repo.bucket_path = integration.key

            actions_list.append(out_repo)

        output = OutputFile(dry_run=dry_run, repos=actions_list)

        if self.params.output_file:
            try:
                with open(
                    self.params.output_file, "w", encoding="locale"
                ) as output_file:
                    yaml.safe_dump(
                        data=output.dict(),
                        stream=output_file,
                        explicit_start=True,
                    )
            except FileNotFoundError:
                raise ParameterError(f"Unable to write to '{self.params.output_file}'")
        else:
            print(yaml.safe_dump(data=output.dict(), explicit_start=True))

        return output

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
                repo = TerraformRepoV1.parse_obj(value)
                repo_list.append(repo)

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
                logging.info([
                    "delete_repo",
                    change_val.desired.account.name,
                    change_key,
                ])
                output.append(change_val.desired)
            else:
                logging.info([
                    "update_repo",
                    change_val.desired.account.name,
                    change_key,
                ])
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
        state: State | None,
        recreate_state: bool,
    ) -> list[TerraformRepoV1] | None:
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
        :param recreate_state: whether we are recreating our own state
        :type recreate_state: bool
        :raises ParameterError: if there is an invalid operation performed like trying to delete
        a representation in A-I before setting the delete flag
        :return: the terraform repo to act on
        :rtype: TerraformRepoV1
        """
        diff = diff_iterables(existing_state, desired_state, lambda x: x.name)

        merged = self.merge_results(diff)

        # validate that only one repo is being modified in each MR
        # this lets us fail early and avoid multiple GL requests we don't need to make
        if dry_run and len(merged) > 1 and not recreate_state:
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
            self.update_mr_with_ref_diffs(diff)
            return merged
        return None

    def update_mr_with_ref_diffs(
        self,
        diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str],
    ) -> None:
        """Heavily "inspired" from the update_mr_with_ref_diffs function
        in saas change deploy tester.
        Adds a comment to GitLab indicating the diffs between an old and new version of
        a Terraform repo.

        :param diff_result: diff between current and desired Terraform Repos
        :type diff_result: DiffResult[TerraformRepoV1, TerraformRepoV1, str]
        """
        if self.params.gitlab_merge_request_id and self.params.gitlab_project_id:
            instance = queries.get_gitlab_instance()
            with GitLabApi(
                instance,
                project_id=self.params.gitlab_project_id,
                settings=queries.get_secret_reader_settings(),
            ) as gl:
                mr = gl.get_merge_request(self.params.gitlab_merge_request_id)

                # construct diff urls
                diff_urls: list[str] = []
                for pair in diff_result.change.values():
                    if pair.current.ref != pair.desired.ref:
                        # gitlab specific syntax
                        diff_urls.append(
                            f"{pair.current.repository}/compare/{pair.current.ref}...{pair.desired.ref}"
                        )

                if len(diff_urls) > 0:
                    comment_body = "tf-repo diffs:\n" + "\n".join([
                        f"- {d}" for d in diff_urls
                    ])
                    gl.delete_merge_request_comments(mr, startswith="tf-repo diffs:")
                    gl.add_comment_to_merge_request(mr, comment_body)

    def early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        gqlapi = gql.get_api()
        return {
            "repos": [repo.dict() for repo in self.get_repos(query_func=gqlapi.query)]
        }
