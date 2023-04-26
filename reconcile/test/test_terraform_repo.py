import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_repo.terraform_repo import (
    AWSAccountV1,
    TerraformRepoV1,
)
from reconcile.terraform_repo import calculate_diff
from reconcile.utils.exceptions import ParameterError


@pytest.fixture
def existing_repo(aws_account) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="a_repo",
        repository="https://gitlab.cee.redhat.com/rywallac/tf-repo-example",
        ref="a390f5cb20322c90861d6d80e9b70c6a579be1d0",
        account=aws_account,
        projectPath="a_repo",
        delete=False,
    )


@pytest.fixture
def new_repo(aws_account) -> TerraformRepoV1:
    return TerraformRepoV1(
        name="b_repo",
        repository="https://gitlab.cee.redhat.com/rywallac/tf-repo-example",
        ref="94edb90815e502b387c25358f5ec602e52d0bfbb",
        account=aws_account,
        projectPath="b_repo",
        delete=False,
    )


@pytest.fixture()
def automation_token() -> VaultSecret:
    return VaultSecret(
        path="aws-secrets/terraform/foo", version=1, field="all", format=None
    )


@pytest.fixture
def aws_account(automation_token) -> AWSAccountV1:
    return AWSAccountV1(
        name="foo",
        uid="000000000000",
        automationToken=automation_token,
    )


def test_addition_to_existing_repo(existing_repo, new_repo):
    existing = [existing_repo]
    desired = [existing_repo, new_repo]
    diff = calculate_diff(existing, desired, True, None)

    assert diff == [new_repo]


def test_updating_repo_ref(existing_repo):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.ref = "94edb90815e502b387c25358f5ec602e52d0bfbb"

    diff = calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


def test_fail_on_update_invalid_repo_params(existing_repo):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.name = "c_repo"
    updated_repo.project_path = "c_repo"
    updated_repo.repository = "https://gitlab.cee.redhat.com/rywallac/tf-repo-example-2"
    updated_repo.ref = "94edb90815e502b387c25358f5ec602e52d0bfbb"
    updated_repo.delete = True
    with pytest.raises(ParameterError):
        calculate_diff(existing, [updated_repo], True, None)


def test_delete_repo(existing_repo):
    existing = [existing_repo]
    updated_repo = TerraformRepoV1.copy(existing_repo)
    updated_repo.delete = True

    diff = calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


def test_delete_repo_without_flag(existing_repo):
    existing = [existing_repo]

    with pytest.raises(ParameterError):
        calculate_diff(existing, [], True, None)
