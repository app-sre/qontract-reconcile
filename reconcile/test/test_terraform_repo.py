import pytest

from reconcile.terraform_repo import (
    AWSAccount,
    AWSAuthSecret,
    TFRepo,
    calculate_diff,
)
from reconcile.utils.exceptions import ParameterError


@pytest.fixture
def existing_repo(aws_account) -> TFRepo:
    return TFRepo(
        name="a_repo",
        repository="https://gitlab.cee.redhat.com/rywallac/tf-repo-example",
        ref="a390f5cb20322c90861d6d80e9b70c6a579be1d0",
        account=aws_account,
        project_path="a_repo",
        delete=False,
    )


@pytest.fixture
def new_repo(aws_account) -> TFRepo:
    return TFRepo(
        name="b_repo",
        repository="https://gitlab.cee.redhat.com/rywallac/tf-repo-example",
        ref="94edb90815e502b387c25358f5ec602e52d0bfbb",
        account=aws_account,
        project_path="b_repo",
        delete=False,
    )


@pytest.fixture
def aws_account() -> AWSAccount:
    return AWSAccount(
        name="foo",
        uid="000000000000",
        secret=AWSAuthSecret(path="aws-secrets/terraform/foo", version=1),
    )


def test_addition_to_existing_repo(existing_repo, new_repo):
    existing = [existing_repo]
    desired = [existing_repo, new_repo]
    diff = calculate_diff(existing, desired, True, None)

    assert diff == [new_repo]


def test_updating_repo_ref(existing_repo):
    existing = [existing_repo]
    updated_repo = TFRepo.parse_obj(existing_repo)
    updated_repo.ref = "94edb90815e502b387c25358f5ec602e52d0bfbb"

    diff = calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


def test_fail_on_update_invalid_repo_params(existing_repo):
    existing = [existing_repo]
    updated_repo = TFRepo.parse_obj(existing_repo)
    updated_repo.name = "c_repo"
    updated_repo.project_path = "c_repo"
    updated_repo.repository = "https://gitlab.cee.redhat.com/rywallac/tf-repo-example-2"
    updated_repo.ref = "94edb90815e502b387c25358f5ec602e52d0bfbb"
    updated_repo.delete = True
    with pytest.raises(ParameterError):
        calculate_diff(existing, [updated_repo], True, None)


def test_delete_repo(existing_repo):
    existing = [existing_repo]
    updated_repo = TFRepo.parse_obj(existing_repo)
    updated_repo.delete = True

    diff = calculate_diff(existing, [updated_repo], True, None)

    assert diff == [updated_repo]


def test_delete_repo_without_flag(existing_repo):
    existing = [existing_repo]

    with pytest.raises(ParameterError):
        calculate_diff(existing, [], True, None)
