import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    AWSAccountV1,
    TerraformRepoV1,
)
from reconcile.terraform_repo import (
    TerraformRepoIntegration,
    TerraformRepoIntegrationParams,
)
from reconcile.utils.exceptions import ParameterError

A_REPO = "https://git-example/tf-repo-example"
A_REPO_SHA = "a390f5cb20322c90861d6d80e9b70c6a579be1d0"
B_REPO = "https://git-example/tf-repo-example2"
B_REPO_SHA = "94edb90815e502b387c25358f5ec602e52d0bfbb"
AWS_UID = "000000000000"
AUTOMATION_TOKEN_PATH = "aws-secrets/terraform/foo"


@pytest.fixture
def existing_repo(aws_account) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="a_repo",
        repository=A_REPO,
        ref=A_REPO_SHA,
        account=aws_account,
        projectPath="tf",
        delete=False,
    )


@pytest.fixture
def new_repo(aws_account) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="b_repo",
        repository=B_REPO,
        ref=B_REPO_SHA,
        account=aws_account,
        projectPath="tf",
        delete=False,
    )


@pytest.fixture()
def automation_token() -> VaultSecret:
    return VaultSecret(path=AUTOMATION_TOKEN_PATH, version=1, field="all", format=None)


@pytest.fixture
def aws_account(automation_token) -> AWSAccountV1:
    return AWSAccountV1(
        name="foo",
        uid="000000000000",
        automationToken=automation_token,
    )


@pytest.fixture
def int_params() -> TerraformRepoIntegrationParams:
    return TerraformRepoIntegrationParams(print_to_file=None, validate_git=False)


def test_addition_to_existing_repo(existing_repo, new_repo, int_params):
    existing = [existing_repo]
    desired = [existing_repo, new_repo]

    integration = TerraformRepoIntegration(params=int_params)
    diff = integration.calculate_diff(existing, desired, True, None)

    assert diff == [new_repo]


def test_updating_repo_ref(existing_repo, int_params):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.ref = B_REPO_SHA

    integration = TerraformRepoIntegration(params=int_params)
    diff = integration.calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


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
        integration.calculate_diff(existing, [updated_repo], True, None)


def test_delete_repo(existing_repo, int_params):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.delete = True

    integration = TerraformRepoIntegration(params=int_params)

    diff = integration.calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


def test_delete_repo_without_flag(existing_repo, int_params):
    existing = [existing_repo]

    integration = TerraformRepoIntegration(params=int_params)

    with pytest.raises(ParameterError):
        integration.calculate_diff(existing, [], True, None)


def test_get_repo_state(s3_state_builder, int_params, existing_repo):
    state = s3_state_builder(
        {
            "ls": [
                "/a_repo",
            ],
            "get": {
                # terraform repo expects a JSON string not a dict so we have to encode a multi-line JSON string
                "a_repo": f"""
                {{
                    "name": "a_repo",
                    "repository": "{A_REPO}",
                    "ref": "{A_REPO_SHA}",
                    "projectPath": "tf",
                    "delete": false,
                    "account": {{
                        "name": "foo",
                        "uid": "{AWS_UID}",
                        "automationToken": {{
                            "path": "{AUTOMATION_TOKEN_PATH}",
                            "field": "all",
                            "version": 1,
                            "format": null
                        }}
                    }}
                }}
                """
            },
        }
    )

    integration = TerraformRepoIntegration(params=int_params)

    existing_state = integration.get_existing_state(state=state)
    assert existing_state == [existing_repo]
