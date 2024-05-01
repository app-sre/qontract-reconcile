from unittest.mock import MagicMock

import pytest

from reconcile.gql_definitions.fragments.terraform_state import (
    AWSTerraformStateIntegrationsV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    AWSAccountV1,
    TerraformRepoV1,
    TerraformRepoVariablesV1,
    TerraformStateAWSV1,
)
from reconcile.terraform_repo import (
    OutputFile,
    RepoOutput,
    TerraformRepoIntegration,
    TerraformRepoIntegrationParams,
)
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.state import State

A_REPO = "https://git-example/tf-repo-example"
A_REPO_SHA = "a390f5cb20322c90861d6d80e9b70c6a579be1d0"
A_REPO_VERSION = "1.4.5"
B_REPO = "https://git-example/tf-repo-example2"
B_REPO_SHA = "94edb90815e502b387c25358f5ec602e52d0bfbb"
B_REPO_VERSION = "1.6.6"
AWS_UID = "000000000000"
AUTOMATION_TOKEN_PATH = "aws-secrets/terraform/foo"
STATE_REGION = "us-east-1"
STATE_BUCKET = "app-sre"
STATE_PROVIDER = "s3"


@pytest.fixture
def existing_repo(aws_account, tf_variables) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="a_repo",
        repository=A_REPO,
        ref=A_REPO_SHA,
        account=aws_account,
        projectPath="tf",
        delete=False,
        requireFips=True,
        tfVersion=A_REPO_VERSION,
        variables=tf_variables,
    )


@pytest.fixture
def existing_repo_output(tf_variables) -> OutputFile:
    return OutputFile(
        dry_run=True,
        repos=[
            RepoOutput(
                repository=A_REPO,
                name="a_repo",
                ref=A_REPO_SHA,
                project_path="tf",
                delete=False,
                aws_creds=VaultSecret(
                    path=AUTOMATION_TOKEN_PATH, version=1, field="all", format=None
                ),
                bucket=STATE_BUCKET,
                region=STATE_REGION,
                bucket_path="tf-repo",
                require_fips=True,
                tf_version=A_REPO_VERSION,
                variables=tf_variables,
            )
        ],
    )


@pytest.fixture
def new_repo(aws_account_no_state) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="b_repo",
        repository=B_REPO,
        ref=B_REPO_SHA,
        account=aws_account_no_state,
        projectPath="tf",
        delete=False,
        requireFips=False,
        tfVersion=B_REPO_VERSION,
        variables=None,
    )


@pytest.fixture
def new_repo_output() -> OutputFile:
    return OutputFile(
        dry_run=True,
        repos=[
            RepoOutput(
                repository=B_REPO,
                name="b_repo",
                ref=B_REPO_SHA,
                project_path="tf",
                delete=False,
                aws_creds=VaultSecret(
                    path=AUTOMATION_TOKEN_PATH, version=1, field="all", format=None
                ),
                bucket=None,
                region=None,
                bucket_path=None,
                require_fips=False,
                tf_version=B_REPO_VERSION,
                variables=None,
            )
        ],
    )


@pytest.fixture()
def automation_token() -> VaultSecret:
    return VaultSecret(path=AUTOMATION_TOKEN_PATH, version=1, field="all", format=None)


@pytest.fixture()
def tf_variables() -> TerraformRepoVariablesV1:
    return TerraformRepoVariablesV1(
        inputs=VaultSecret(
            path="terraform-repo/inputs/abc", field="all", version=2, format=None
        ),
        outputs=VaultSecret(
            path="terraform-repo/outputs/abc", field="all", version=2, format=None
        ),
    )


@pytest.fixture()
def terraform_state(terraform_state_integrations) -> TerraformStateAWSV1:
    return TerraformStateAWSV1(
        provider=STATE_PROVIDER,
        region=STATE_REGION,
        bucket=STATE_BUCKET,
        integrations=terraform_state_integrations,
    )


@pytest.fixture()
def terraform_state_integrations() -> list[AWSTerraformStateIntegrationsV1]:
    return [
        AWSTerraformStateIntegrationsV1(integration="terraform-repo", key="tf-repo")
    ]


@pytest.fixture
def aws_account(automation_token, terraform_state) -> AWSAccountV1:
    return AWSAccountV1(
        name="foo",
        uid="000000000000",
        automationToken=automation_token,
        terraformState=terraform_state,
    )


@pytest.fixture
def aws_account_no_state(automation_token) -> AWSAccountV1:
    return AWSAccountV1(
        name="foo",
        uid="000000000000",
        automationToken=automation_token,
        terraformState=None,
    )


@pytest.fixture
def int_params() -> TerraformRepoIntegrationParams:
    return TerraformRepoIntegrationParams(output_file=None, validate_git=False)


@pytest.fixture()
def state_mock() -> MagicMock:
    return MagicMock(spec=State)


def test_addition_to_existing_repo(existing_repo, new_repo, int_params, state_mock):
    existing = [existing_repo]
    desired = [existing_repo, new_repo]

    integration = TerraformRepoIntegration(params=int_params)
    diff = integration.calculate_diff(
        existing_state=existing,
        desired_state=desired,
        dry_run=False,
        state=state_mock,
        recreate_state=False,
    )

    assert diff == [new_repo]

    # ensure that the state is saved for the new repo
    state_mock.add.assert_called_once_with(
        new_repo.name, new_repo.dict(by_alias=True), force=True
    )


def test_updating_repo_ref(existing_repo, int_params, state_mock):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.ref = B_REPO_SHA

    integration = TerraformRepoIntegration(params=int_params)
    diff = integration.calculate_diff(
        existing_state=existing,
        desired_state=[updated_repo],
        dry_run=False,
        state=state_mock,
        recreate_state=False,
    )

    assert diff == [updated_repo]

    state_mock.add.assert_called_once_with(
        updated_repo.name, updated_repo.dict(by_alias=True), force=True
    )


def test_fail_on_update_invalid_repo_params(existing_repo, int_params):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.name = "c_repo"
    updated_repo.project_path = "c_repo"
    updated_repo.repository = B_REPO
    updated_repo.ref = B_REPO_SHA
    updated_repo.delete = True

    integration = TerraformRepoIntegration(params=int_params)

    with pytest.raises(ParameterError):
        integration.calculate_diff(
            existing_state=existing,
            desired_state=[updated_repo],
            dry_run=True,
            state=None,
            recreate_state=False,
        )


def test_delete_repo(existing_repo, int_params, state_mock):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.delete = True

    integration = TerraformRepoIntegration(params=int_params)

    diff = integration.calculate_diff(
        existing_state=existing,
        desired_state=[updated_repo],
        dry_run=False,
        state=state_mock,
        recreate_state=False,
    )

    assert diff == [updated_repo]

    state_mock.rm.assert_called_once_with(updated_repo.name)


def test_delete_repo_without_flag(existing_repo, int_params):
    existing = [existing_repo]

    integration = TerraformRepoIntegration(params=int_params)

    with pytest.raises(ParameterError):
        integration.calculate_diff(
            existing_state=existing,
            desired_state=[],
            dry_run=True,
            state=None,
            recreate_state=False,
        )


def test_get_repo_state(s3_state_builder, int_params, existing_repo, tf_variables):
    state = s3_state_builder({
        "ls": [
            "/a_repo",
        ],
        "get": {
            "a_repo": {
                "name": "a_repo",
                "repository": A_REPO,
                "ref": A_REPO_SHA,
                "projectPath": "tf",
                "delete": False,
                "requireFips": True,
                "tfVersion": A_REPO_VERSION,
                "variables": tf_variables,
                "account": {
                    "name": "foo",
                    "uid": AWS_UID,
                    "automationToken": {
                        "path": AUTOMATION_TOKEN_PATH,
                        "field": "all",
                        "version": 1,
                        "format": None,
                    },
                    "terraformState": {
                        "provider": "s3",
                        "region": "us-east-1",
                        "bucket": "app-sre",
                        "integrations": [
                            {
                                "integration": "terraform-repo",
                                "key": "tf-repo",
                            }
                        ],
                    },
                },
            }
        },
    })

    integration = TerraformRepoIntegration(params=int_params)

    existing_state = integration.get_existing_state(state=state)
    assert existing_state == [existing_repo]


def test_update_repo_state(int_params, existing_repo, state_mock):
    integration = TerraformRepoIntegration(params=int_params)

    existing_state: list = []
    desired_state = [existing_repo]

    integration.calculate_diff(
        existing_state=existing_state,
        desired_state=desired_state,
        dry_run=False,
        state=state_mock,
        recreate_state=False,
    )

    state_mock.add.assert_called_once_with(
        existing_repo.name, existing_repo.dict(by_alias=True), force=True
    )


# these two output tests are to ensure that there isn't a sudden change to outputs that throws
# off tf-executor
def test_output_correct_statefile(
    int_params, existing_repo, existing_repo_output, state_mock
):
    integration = TerraformRepoIntegration(params=int_params)

    existing_state: list = []
    desired_state = [existing_repo]

    diff = integration.calculate_diff(
        existing_state=existing_state,
        desired_state=desired_state,
        dry_run=True,
        state=state_mock,
        recreate_state=False,
    )

    assert diff
    current_output = integration.print_output(diff, True)

    assert existing_repo_output == current_output


def test_output_correct_no_statefile(
    int_params, new_repo, new_repo_output, tmp_path, state_mock
):
    integration = TerraformRepoIntegration(params=int_params)

    existing_state: list = []
    desired_state = [new_repo]

    diff = integration.calculate_diff(
        existing_state=existing_state,
        desired_state=desired_state,
        dry_run=True,
        state=state_mock,
        recreate_state=False,
    )

    assert diff
    current_output = integration.print_output(diff, True)

    assert new_repo_output == current_output


def test_fail_on_multiple_repos_dry_run(int_params, existing_repo, new_repo):
    integration = TerraformRepoIntegration(params=int_params)

    desired_state = [existing_repo, new_repo]

    with pytest.raises(Exception):
        integration.calculate_diff(
            existing_state=[],
            desired_state=desired_state,
            dry_run=True,
            state=None,
            recreate_state=False,
        )


def test_succeed_on_multiple_repos_non_dry_run(int_params, existing_repo, new_repo):
    integration = TerraformRepoIntegration(params=int_params)

    desired_state = [existing_repo, new_repo]

    diff = integration.calculate_diff(
        existing_state=[],
        desired_state=desired_state,
        dry_run=False,
        state=None,
        recreate_state=False,
    )

    assert diff
    if diff:
        assert diff.sort(key=lambda r: r.name) == desired_state.sort(
            key=lambda r: r.name
        )


def test_no_op_succeeds(int_params, existing_repo):
    integration = TerraformRepoIntegration(params=int_params)

    state = [existing_repo]

    diff = integration.calculate_diff(
        existing_state=state,
        desired_state=state,
        dry_run=True,
        state=None,
        recreate_state=False,
    )

    assert diff is None
