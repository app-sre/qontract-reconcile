from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws

from reconcile.utils.state import State
from tools import iam_key_rotation_lock as locks
from tools import rotate_erv2_cloudwatch_keys as erv2
from tools import rotate_terraform_resources_keys as legacy

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_mock import MockerFixture


@pytest.fixture
def state(mocker: MockerFixture) -> Generator[State]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="rotation-locks")
        state = State("iam-key-rotation-locks", "rotation-locks", client)
        mocker.patch.object(locks, "init_state", return_value=state)
        yield state


def test_exclusive_acquisition_and_reuse_after_release(state: State) -> None:
    scope = locks.iam_user_scope("111122223333", "example")
    with locks.operation_lock(None, [scope]):
        with (
            pytest.raises(erv2.RotationError, match="Another rotation holds"),
            locks.operation_lock(None, [scope]),
        ):
            pytest.fail("A concurrent operation acquired the same lock")
        assert state.exists(scope)
    assert not state.exists(scope)
    with locks.operation_lock(None, [scope]):
        assert state.exists(scope)


def test_body_failure_releases_lock(state: State) -> None:
    with (
        pytest.raises(ValueError, match="operation failed"),
        locks.operation_lock(None, ["test"]),
    ):
        raise ValueError("operation failed")
    assert not state.exists("test")


@pytest.mark.parametrize("fail_body", [False, True])
def test_release_cannot_delete_another_owner(state: State, fail_body: bool) -> None:
    expected = ValueError if fail_body else erv2.RotationError

    def replace_owner() -> None:
        with locks.operation_lock(None, ["test"]):
            state.client.put_object(
                Bucket=state.bucket,
                Key=state.state_path + "/test",
                Body=b"different owner",
            )
            if fail_body:
                raise ValueError("original failure")

    with pytest.raises(expected):
        replace_owner()
    assert state.exists("test")


@pytest.mark.parametrize("fail_body", [False, True])
def test_release_transport_error_reports_lock(
    state: State,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
    fail_body: bool,
) -> None:
    mocker.patch.object(
        state.client,
        "delete_object",
        side_effect=EndpointConnectionError(endpoint_url="https://example.invalid"),
    )
    lock_uri = f"s3://{state.bucket}/{state.state_path}/test"
    expected = ValueError if fail_body else erv2.RotationError
    match = "original failure" if fail_body else lock_uri

    body = mocker.Mock(
        side_effect=ValueError("original failure") if fail_body else None
    )
    with pytest.raises(expected, match=match), locks.operation_lock(None, ["test"]):
        body()

    if fail_body:
        assert lock_uri in capsys.readouterr().err


def test_legacy_preparation_and_retirement_share_the_iam_user_lock(
    state: State,
) -> None:
    retire = legacy.RetirementClient.__new__(legacy.RetirementClient)
    retire.reader = None
    retire.target = legacy.RetirementTarget(
        account="alias",
        account_id="111122223333",
        iam_user="example",
        region="us-east-1",
    )
    prepare = legacy.Runtime.__new__(legacy.Runtime)
    prepare.reader = None  # type: ignore[assignment]
    prepare.target = legacy.Target(
        account="another-alias",
        account_id="111122223333",
        iam_user="example",
        bucket="test-state",
        key="terraform.tfstate",
        region="us-east-1",
        bindings=[],
    )
    with (
        retire.lock(),
        pytest.raises(erv2.RotationError, match="Another rotation holds"),
        prepare.lock(),
    ):
        pytest.fail("Legacy preparation ignored retirement")


def test_different_users_cannot_edit_one_legacy_state_concurrently(
    state: State,
) -> None:
    first = legacy.Runtime.__new__(legacy.Runtime)
    first.reader = None  # type: ignore[assignment]
    first.target = legacy.Target(
        account="test",
        account_id="111122223333",
        iam_user="first",
        bucket="test-state",
        key="terraform.tfstate",
        region="us-east-1",
        bindings=[],
    )
    second = legacy.Runtime.__new__(legacy.Runtime)
    second.reader = None  # type: ignore[assignment]
    second.target = first.target.model_copy(update={"iam_user": "second"})
    with first.lock():
        with (
            pytest.raises(erv2.RotationError, match="Another rotation holds"),
            second.lock(),
        ):
            pytest.fail("Two users mutated the same state")
        # The failed multi-lock acquisition must release its own user lock.
        with locks.operation_lock(
            None, [locks.iam_user_scope("111122223333", "second")]
        ):
            pass


def test_erv2_and_retirement_share_the_same_user_lock(state: State) -> None:
    retire = legacy.RetirementClient.__new__(legacy.RetirementClient)
    retire.reader = None
    retire.target = legacy.RetirementTarget(
        account="alias",
        account_id="111122223333",
        iam_user="example",
        region="us-east-1",
    )
    external = erv2.Runtime.__new__(erv2.Runtime)
    external.reader = None  # type: ignore[assignment]
    target = erv2.Target(
        account="another-alias",
        account_id="111122223333",
        identifier="example",
        region="us-east-1",
    )
    with (
        retire.lock(),
        pytest.raises(erv2.RotationError, match="Another rotation holds"),
        external.lock(target),
    ):
        pytest.fail("ERv2 preparation ignored retirement")
