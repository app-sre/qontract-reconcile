from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Literal

import pytest
from click.testing import CliRunner

from reconcile.gql_definitions.external_resources import aws_account_identities
from tools import qontract_cli
from tools import rotate_erv2_cloudwatch_keys as rotation

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from unittest.mock import Mock

    from pytest_mock import MockerFixture

OLD = "AKIA" + "A" * 16
NEW = "AKIA" + "B" * 16


@pytest.fixture
def target() -> rotation.Target:
    return rotation.Target(
        account="test-account",
        account_id="111122223333",
        identifier="test-cw",
        region="us-east-1",
    )


@pytest.fixture
def runtime(mocker: MockerFixture) -> Mock:
    runtime = mocker.Mock(spec=rotation.RotationRuntime)
    runtime.lock.side_effect = lambda _: nullcontext()
    runtime.state = rotation.KeyState(key_id=OLD, user="test-cw", tainted=False)
    runtime.keys = [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    runtime.er_status = "CREATED"
    runtime.removals = 0
    runtime.taints = 0
    runtime.requests = 0
    runtime.fail_remove = False
    runtime.lose_request_response = False

    def operation(
        target: rotation.Target,
        action: Literal["inspect", "remove", "taint"],
        expected_key: str | None = None,
    ) -> rotation.KeyState:
        if action == "remove":
            assert expected_key == runtime.state.key_id
            runtime.removals += 1
            runtime.state.key_id = None
            if runtime.fail_remove:
                raise rotation.RotationError("simulated interrupted state removal")
        if action == "taint":
            assert expected_key == runtime.state.key_id
            runtime.taints += 1
            runtime.state.tainted = True
        return runtime.state.model_copy()

    def request(target: rotation.Target) -> None:
        runtime.requests += 1
        runtime.er_status = "RECONCILIATION_REQUESTED"
        if runtime.lose_request_response:
            raise rotation.RotationError("simulated lost response")

    runtime.operation.side_effect = operation
    runtime.request.side_effect = request
    runtime.iam_keys.side_effect = lambda _: runtime.keys
    runtime.key_last_used.return_value = rotation.IamKeyLastUsed()
    runtime.status.side_effect = lambda _: runtime.er_status
    return runtime


def request(**kwargs: str | bool | None) -> rotation.Request:
    return rotation.Request(account="test-account", identifier="test-cw", **kwargs)


def test_inspection_has_no_mutations(target: rotation.Target, runtime: Mock) -> None:
    result = rotation.rotate(request(), target, runtime)
    assert (runtime.removals, runtime.requests) == (0, 0)
    assert result.status == "would_rotate"
    assert result.access_key_id == OLD
    assert result.exit_code == 0
    assert result.iam_keys[0].matches_terraform_binding is True
    runtime.lock.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        {"dry_run": False},
        {"verify": True},
        {"dry_run": False, "verify": True, "expected_key_id": OLD},
    ],
)
def test_required_preconditions_before_any_state_access(
    target: rotation.Target, runtime: Mock, options: dict[str, str | bool]
) -> None:
    with pytest.raises(rotation.RotationError):
        rotation.rotate(request(**options), target, runtime)
    runtime.operation.assert_not_called()


def test_execution_forgets_old_key_without_retiring_it_and_requests_reconciliation(
    target: rotation.Target, runtime: Mock
) -> None:
    result = rotation.rotate(
        request(dry_run=False, expected_key_id=OLD), target, runtime
    )
    assert result.status == "requested"
    assert (runtime.removals, runtime.requests) == (1, 1)
    assert result.access_key_id is None
    assert result.retained_key_id == OLD
    assert runtime.keys == [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    assert not result.tainted
    runtime.operation.assert_any_call(target, "remove", OLD)


def test_expected_key_inspection_and_mutation_share_exclusive_access(
    target: rotation.Target, runtime: Mock
) -> None:
    held = False

    @contextmanager
    def lock(_target: rotation.Target) -> Generator[None]:
        nonlocal held
        if held:
            raise rotation.RotationError("another preparation holds the lock")
        held = True
        try:
            yield
        finally:
            held = False

    runtime.lock.side_effect = lock
    original = runtime.operation.side_effect

    def operation(
        target: rotation.Target,
        action: Literal["inspect", "remove", "taint"],
        expected_key: str | None = None,
    ) -> rotation.KeyState:
        assert held
        if action == "inspect":
            calls = runtime.operation.call_count
            with pytest.raises(rotation.RotationError, match="another preparation"):
                rotation.rotate(
                    request(dry_run=False, expected_key_id=OLD), target, runtime
                )
            assert runtime.operation.call_count == calls
        return original(target, action, expected_key)

    runtime.operation.side_effect = operation
    assert (
        rotation.rotate(
            request(dry_run=False, expected_key_id=OLD), target, runtime
        ).status
        == "requested"
    )
    assert not held


def test_repeat_call_while_pending_does_not_remove_state_again(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    rotation.rotate(command, target, runtime)
    result = rotation.rotate(command, target, runtime)
    assert result.status == "pending"
    assert result.exit_code == 2
    assert (runtime.removals, runtime.requests) == (1, 1)


def test_stale_expected_key_cannot_rotate_replacement(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = NEW
    result = rotation.rotate(
        request(dry_run=False, expected_key_id=OLD), target, runtime
    )
    assert result.status == "key_changed"
    assert result.exit_code == 2
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_interrupted_removal_resumes_without_forgetting_another_key(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    runtime.fail_remove = True
    with pytest.raises(rotation.RotationError, match="interrupted state removal"):
        rotation.rotate(command, target, runtime)
    result = rotation.rotate(command, target, runtime)
    assert result.status == "requested"
    assert (runtime.removals, runtime.requests) == (1, 1)


def test_lost_request_response_does_not_repeat_rotation(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    runtime.lose_request_response = True
    with pytest.raises(rotation.RotationError, match="lost response"):
        rotation.rotate(command, target, runtime)
    assert rotation.rotate(command, target, runtime).status == "pending"
    assert (runtime.removals, runtime.requests) == (1, 1)


@pytest.mark.parametrize("status", ["ERROR", "NOT_EXISTS", "DELETE_IN_PROGRESS"])
def test_failed_or_deleted_resource_stops_execution(
    target: rotation.Target, runtime: Mock, status: str
) -> None:
    runtime.er_status = status
    with pytest.raises(rotation.RotationError, match="investigate"):
        rotation.rotate(request(dry_run=False, expected_key_id=OLD), target, runtime)
    assert (runtime.removals, runtime.requests) == (0, 0)


@pytest.mark.parametrize(
    ("old_present", "active", "tainted", "status", "expected"),
    [
        (True, True, False, "CREATED", "ready_for_cutover"),
        (False, False, False, "CREATED", "pending"),
        (False, True, False, "PENDING_SECRET_SYNC", "pending"),
        (False, True, True, "CREATED", "pending"),
        (False, True, False, "CREATED", "replaced"),
    ],
)
def test_verification_distinguishes_cutover_readiness_from_old_key_retirement(
    target: rotation.Target,
    runtime: Mock,
    old_present: bool,
    active: bool,
    tainted: bool,
    status: str,
    expected: str,
) -> None:
    runtime.state = rotation.KeyState(key_id=NEW, user="test-cw", tainted=tainted)
    runtime.keys = [
        rotation.IamKey(AccessKeyId=NEW, Status="Active" if active else "Inactive")
    ]
    if old_present:
        runtime.keys.append(rotation.IamKey(AccessKeyId=OLD, Status="Active"))
    runtime.er_status = status
    result = rotation.rotate(request(verify=True, expected_key_id=OLD), target, runtime)
    assert result.status == expected
    assert (runtime.removals, runtime.requests) == (0, 0)
    assert result.retained_key_id == (OLD if old_present else None)
    runtime.lock.assert_not_called()


def test_subprocess_failure_does_not_expose_output(mocker: MockerFixture) -> None:
    mocker.patch.object(
        rotation.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 1, stdout="test-only-secret", stderr="test-only-secret"
        ),
    )
    with pytest.raises(rotation.RotationError) as result:
        rotation.checked(["example"], phase="test")
    assert "test-only-secret" not in str(result.value)


@pytest.fixture
def terraform_state() -> rotation.TerraformState:
    return rotation.TerraformState.model_validate({
        "resources": [
            {
                "mode": "managed",
                "type": "aws_iam_access_key",
                "name": "this",
                "instances": [
                    {
                        "attributes": {
                            "id": OLD,
                            "user": "test-cw",
                            "secret": "test-only-secret",
                        }
                    }
                ],
            }
        ]
    })


def test_state_metadata_excludes_secret_and_rejects_wrong_user(
    terraform_state: rotation.TerraformState,
) -> None:
    assert rotation.state_metadata(terraform_state, "test-cw") == rotation.KeyState(
        key_id=OLD, user="test-cw", tainted=False
    )
    with pytest.raises(rotation.RotationError, match="Unexpected access-key"):
        rotation.state_metadata(terraform_state, "different-user")


def test_container_refuses_to_forget_changed_key(
    tmp_path: Path,
    terraform_state: rotation.TerraformState,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    terraform_state.resources[0].instances[0].attributes["id"] = NEW
    source = tmp_path / "module"
    source.mkdir()
    monkeypatch.setenv("TERRAFORM_MODULE_SRC_DIR", str(source))
    monkeypatch.setenv("TERRAFORM_MODULE_WORK_DIR", str(tmp_path / "work"))
    commands = mocker.patch.object(
        rotation, "checked", side_effect=["", "", terraform_state.model_dump_json()]
    )
    with pytest.raises(rotation.RotationError, match="no mutation attempted"):
        rotation.container_operation("remove", "test-cw", OLD)
    assert not any("rm" in call.args[0] for call in commands.call_args_list)


def test_wrong_aws_account_stops_before_container(
    tmp_path: Path, target: rotation.Target, mocker: MockerFixture
) -> None:
    mocker.patch(
        "tools.qontract_cli._get_external_resources_credentials",
        return_value="test-only-credential",
    )
    runtime = rotation.Runtime.__new__(rotation.Runtime)
    runtime.directory = tmp_path
    runtime.reader = mocker.Mock()
    runtime.credentials = {}
    runtime.backend = rotation.Backend(
        account_id="444455556666", bucket="test-state", region="us-east-1"
    )
    data = {
        "data": {"identifier": "test-cw", "region": "us-east-1"},
        "provision": {
            "provision_provider": "aws",
            "provisioner": "test-account",
            "provider": "cloudwatch",
            "identifier": "test-cw",
            "target_cluster": "test-cluster",
            "target_namespace": "test-namespace",
            "target_secret_name": "test-secret",
            "module_provision_data": {
                "tf_state_bucket": "test-state",
                "tf_state_region": "us-east-1",
                "tf_state_key": "aws/test-account/cloudwatch/test-cw/terraform.tfstate",
            },
        },
    }
    mocker.patch.object(
        runtime, "client", return_value=mocker.Mock(input_data=json.dumps(data))
    )
    mocker.patch.object(
        runtime, "aws", return_value=json.dumps({"Account": "999900001111"})
    )
    with pytest.raises(rotation.RotationError, match="AWS identity mismatch"):
        runtime.prepare(target)
    assert not runtime.credentials


def test_execute_preconditions_before_client_construction(
    mocker: MockerFixture,
) -> None:
    client = mocker.patch("tools.cli_commands.erv2.Erv2Cli")
    with pytest.raises(rotation.RotationError, match="expected-key-id"):
        rotation.run_single("test-account", "test-cw", mocker.Mock(), dry_run=False)
    client.assert_not_called()


@pytest.fixture
def cli_setup(mocker: MockerFixture) -> Mock:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    return mocker.patch.object(qontract_cli, "create_secret_reader")


def cli_args(provider: str = "cloudwatch") -> list[str]:
    return [
        "--provision-provider",
        "aws",
        "--provisioner",
        "test-account",
        "--provider",
        provider,
        "--identifier",
        "test-cw",
        "rotate-access-key",
    ]


def result(
    status: Literal["would_rotate", "pending"] = "would_rotate",
) -> rotation.Result:
    return rotation.Result(
        account="test-account",
        identifier="test-cw",
        status=status,
        access_key_id=OLD,
        expected_key_id=None,
        resource_status="CREATED",
        tainted=False,
    )


def test_native_cli_defaults_to_one_resource_inspection(
    cli_setup: Mock, mocker: MockerFixture
) -> None:
    run = mocker.patch.object(rotation, "run_single", return_value=result())
    response = CliRunner().invoke(qontract_cli.external_resources, cli_args(), obj={})
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["access_key_id"] == OLD
    run.assert_called_once_with(
        provisioner="test-account",
        identifier="test-cw",
        secret_reader=cli_setup.return_value,
        dry_run=True,
        expected_key_id=None,
        verify=False,
        mode="without-downtime",
    )


@pytest.mark.parametrize("mode", ["--no-dry-run", "--verify"])
def test_native_cli_forwards_execution_or_verification(
    cli_setup: Mock, mocker: MockerFixture, mode: str
) -> None:
    run = mocker.patch.object(rotation, "run_single", return_value=result("pending"))
    response = CliRunner().invoke(
        qontract_cli.external_resources,
        [*cli_args(), mode, "--expected-key-id", OLD],
        obj={},
    )
    assert response.exit_code == 2, response.output
    assert run.call_args.kwargs["expected_key_id"] == OLD
    assert run.call_args.kwargs["dry_run"] == (mode != "--no-dry-run")
    assert run.call_args.kwargs["verify"] == (mode == "--verify")


def test_native_cli_reuses_root_configuration_once(
    tmp_path: Path, cli_setup: Mock, mocker: MockerFixture
) -> None:
    config = tmp_path / "config.toml"
    config.touch()
    initialize = mocker.patch.object(qontract_cli.config, "init_from_toml")
    graphql = mocker.patch.object(qontract_cli.gql, "init_from_config")
    close = mocker.patch.object(qontract_cli.GqlApiSingleton, "close")
    mocker.patch.object(rotation, "run_single", return_value=result())
    response = CliRunner().invoke(
        qontract_cli.root, ["--config", str(config), "external-resources", *cli_args()]
    )
    assert response.exit_code == 0, response.output
    initialize.assert_called_once_with(str(config))
    graphql.assert_called_once_with()
    close.assert_called_once_with()


def test_native_cli_rejects_other_providers(
    cli_setup: Mock, mocker: MockerFixture
) -> None:
    run = mocker.patch.object(rotation, "run_single")
    response = CliRunner().invoke(
        qontract_cli.external_resources, cli_args("rds"), obj={}
    )
    assert response.exit_code == 1
    assert "only AWS CloudWatch" in response.output
    run.assert_not_called()


def test_native_cli_suppresses_credential_library_errors(
    cli_setup: Mock, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        rotation, "run_single", side_effect=ValueError("test-only-secret")
    )
    response = CliRunner().invoke(qontract_cli.external_resources, cli_args(), obj={})
    assert response.exit_code == 1
    assert "ValueError" in response.output
    assert "test-only-secret" not in response.output


def test_single_resource_resolves_accounts_and_closes_runtime(
    mocker: MockerFixture,
) -> None:
    reader = mocker.Mock()
    client = mocker.patch("tools.cli_commands.erv2.Erv2Cli").return_value
    client.resource_bindings_count = 1
    client.input_data = json.dumps({
        "data": {"identifier": "test-cw", "region": "us-east-1"},
        "provision": {
            "provision_provider": "aws",
            "provisioner": "test-account",
            "provider": "cloudwatch",
            "identifier": "test-cw",
            "target_cluster": "test-cluster",
            "target_namespace": "test-namespace",
            "target_secret_name": "test-secret",
            "module_provision_data": {
                "tf_state_bucket": "test-state",
                "tf_state_region": "us-east-1",
                "tf_state_key": "aws/test-account/cloudwatch/test-cw/terraform.tfstate",
            },
        },
    })
    settings = mocker.patch(
        "reconcile.typed_queries.external_resources.get_settings"
    ).return_value
    settings.state_dynamodb_account.name = "state-account"
    settings.tf_state_bucket = "test-state"
    settings.tf_state_region = "us-east-1"
    mocker.patch.object(
        rotation,
        "account_id",
        side_effect=lambda name: {
            "test-account": "111122223333",
            "state-account": "444455556666",
        }[name],
    )
    factory = mocker.patch.object(rotation, "Runtime")
    runtime = factory.return_value
    runtime.operation.return_value = rotation.KeyState(
        key_id=OLD, user="test-cw", tainted=False
    )
    runtime.iam_keys.return_value = [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    runtime.key_last_used.return_value = rotation.IamKeyLastUsed()
    runtime.status.return_value = "CREATED"
    assert (
        rotation.run_single("test-account", "test-cw", reader).status == "would_rotate"
    )
    factory.assert_called_once_with(
        rotation.Target(
            account="test-account",
            account_id="111122223333",
            identifier="test-cw",
            region="us-east-1",
        ),
        rotation.Backend(
            account_id="444455556666", bucket="test-state", region="us-east-1"
        ),
        reader,
        client,
    )
    runtime.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("dry_run", "verify"), [(True, False), (False, False), (True, True)]
)
def test_single_resource_rejects_shared_namespace_bindings(
    mocker: MockerFixture, dry_run: bool, verify: bool
) -> None:
    client = mocker.patch("tools.cli_commands.erv2.Erv2Cli").return_value
    client.resource_bindings_count = 2
    runtime = mocker.patch.object(rotation, "Runtime")

    with pytest.raises(rotation.RotationError, match="one namespace binding"):
        rotation.run_single(
            "test-account",
            "test-cw",
            mocker.Mock(),
            expected_key_id=OLD,
            dry_run=dry_run,
            verify=verify,
        )

    runtime.assert_not_called()
    client.reconcile.assert_not_called()


@pytest.mark.parametrize(
    "names", [[], ["wrong-account"], ["test-account", "test-account"]]
)
def test_account_identity_rejects_ambiguous_or_missing_results(
    mocker: MockerFixture, names: list[str]
) -> None:
    mocker.patch("reconcile.utils.gql.get_api")
    mocker.patch.object(
        aws_account_identities,
        "query",
        return_value=aws_account_identities.AWSExternalResourceAccountIdentitiesQueryData(
            accounts=[
                aws_account_identities.AWSAccountV1(name=name, uid="111122223333")
                for name in names
            ],
        ),
    )
    with pytest.raises(rotation.RotationError, match="exactly one"):
        rotation.account_id("test-account")


def test_runtime_status_reads_one_resource_without_scanning(
    target: rotation.Target, mocker: MockerFixture
) -> None:
    mocker.patch("reconcile.utils.gql.get_api")
    settings = mocker.patch(
        "reconcile.typed_queries.external_resources.get_settings"
    ).return_value
    settings.state_dynamodb_table = "test-state"
    api = mocker.patch(
        "reconcile.external_resources.integration.get_aws_api"
    ).return_value.__enter__.return_value
    client = api.dynamodb.boto3_client
    client.get_item.return_value = {}
    client.get_paginator.side_effect = AssertionError("A point read must not scan")
    runtime = rotation.Runtime.__new__(rotation.Runtime)
    runtime.reader = mocker.Mock()

    assert runtime.status(target) == "NOT_EXISTS"
    client.get_item.assert_called_once_with(
        TableName="test-state",
        ConsistentRead=True,
        Key={
            "external_resource_key_hash": {"S": "aws/test-account/cloudwatch/test-cw"}
        },
    )
    client.get_paginator.assert_not_called()


def test_verification_reports_iam_key_inventory_without_mutation(
    target: rotation.Target, runtime: Mock
) -> None:
    extra = "AKIA" + "C" * 16
    managed = NEW
    runtime.state.key_id = managed
    runtime.keys = [
        rotation.IamKey(AccessKeyId=managed, Status="Active"),
        rotation.IamKey(AccessKeyId=extra, Status="Active"),
    ]
    result = rotation.rotate(
        rotation.Request(
            account=target.account,
            identifier=target.identifier,
            verify=True,
            expected_key_id=OLD,
        ),
        target,
        runtime,
    )

    assert result.status == "replaced"
    assert [
        (key.access_key_id, key.status, key.matches_terraform_binding)
        for key in result.iam_keys
    ] == [(managed, "Active", True), (extra, "Active", False)]
    assert all(call.args[1] == "inspect" for call in runtime.operation.call_args_list)
    runtime.request.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("extra_status", ["Active", "Inactive"])
def test_existing_second_key_blocks_preparation_without_deleting_any_key(
    target: rotation.Target, runtime: Mock, dry_run: bool, extra_status: str
) -> None:
    runtime.keys.append(rotation.IamKey(AccessKeyId=NEW, Status=extra_status))
    with pytest.raises(rotation.RotationError, match="Both IAM key slots") as exc:
        rotation.rotate(request(dry_run=dry_run, expected_key_id=OLD), target, runtime)
    assert f"{OLD}: Active, matches Terraform binding" in str(exc.value)
    assert (
        f"{NEW}: {extra_status}, does not match Terraform binding, no recorded use"
        in str(exc.value)
    )
    assert "delete-access-key" in str(exc.value)
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_tainted_key_cannot_start_no_downtime_rotation(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.tainted = True
    with pytest.raises(rotation.RotationError, match="already tainted"):
        rotation.rotate(request(dry_run=False, expected_key_id=OLD), target, runtime)
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_missing_state_requires_original_key_id_for_safe_resumption(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = None
    with pytest.raises(rotation.RotationError, match="original --expected-key-id"):
        rotation.rotate(request(), target, runtime)
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_managed_replacement_after_interruption_cannot_be_forgotten(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = NEW
    runtime.keys.append(rotation.IamKey(AccessKeyId=NEW, Status="Active"))
    assert (
        rotation.rotate(
            request(dry_run=False, expected_key_id=OLD), target, runtime
        ).status
        == "key_changed"
    )
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_iam_key_change_during_state_removal_stops_reconciliation(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.iam_keys.side_effect = [
        runtime.keys.copy(),
        [rotation.IamKey(AccessKeyId=NEW, Status="Active")],
    ]
    with pytest.raises(rotation.RotationError, match="IAM keys changed"):
        rotation.rotate(request(dry_run=False, expected_key_id=OLD), target, runtime)
    assert (runtime.removals, runtime.requests) == (1, 0)


def test_inactive_old_key_does_not_report_no_downtime_cutover_readiness(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = NEW
    runtime.keys = [
        rotation.IamKey(AccessKeyId=OLD, Status="Inactive"),
        rotation.IamKey(AccessKeyId=NEW, Status="Active"),
    ]
    assert (
        rotation.rotate(
            request(verify=True, expected_key_id=OLD), target, runtime
        ).status
        == "pending"
    )
    assert (runtime.removals, runtime.requests) == (0, 0)


def test_container_removes_only_key_state_and_preserves_other_resources(
    tmp_path: Path,
    terraform_state: rotation.TerraformState,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    source = tmp_path / "module"
    source.mkdir()
    monkeypatch.setenv("TERRAFORM_MODULE_SRC_DIR", str(source))
    monkeypatch.setenv("TERRAFORM_MODULE_WORK_DIR", str(tmp_path / "work"))
    remaining = rotation.TerraformState.model_validate({
        "resources": [
            {
                "mode": "managed",
                "type": "aws_iam_user",
                "name": "this",
                "instances": [{"attributes": {"id": "test-cw"}}],
            }
        ]
    })
    commands = mocker.patch.object(
        rotation,
        "checked",
        side_effect=[
            "",
            "",
            terraform_state.model_dump_json(),
            "",
            remaining.model_dump_json(),
        ],
    )
    result = rotation.container_operation("remove", "test-cw", OLD)
    assert result.key_id is None and not result.tainted
    assert [call.args[0][2:] for call in commands.call_args_list] == [
        [],
        ["init", "-input=false", "-no-color"],
        ["state", "pull"],
        ["state", "rm", "-lock-timeout=60s", "aws_iam_access_key.this"],
        ["state", "pull"],
    ]


def test_container_refuses_unknown_rotation_operation() -> None:
    with pytest.raises(rotation.RotationError, match="Unknown container operation"):
        rotation.container_operation("destroy", "test-cw", OLD)


def test_explicit_downtime_mode_taints_expected_key_without_removing_state(
    target: rotation.Target, runtime: Mock
) -> None:
    result = rotation.rotate(
        request(mode="with-downtime", dry_run=False, expected_key_id=OLD),
        target,
        runtime,
    )
    assert result.mode == "with-downtime" and result.status == "requested"
    assert result.access_key_id == OLD and result.tainted
    assert (runtime.taints, runtime.removals, runtime.requests) == (1, 0, 1)
    runtime.operation.assert_any_call(target, "taint", OLD)


def test_downtime_mode_inspection_has_no_mutations(
    target: rotation.Target, runtime: Mock
) -> None:
    result = rotation.rotate(request(mode="with-downtime"), target, runtime)
    assert result.mode == "with-downtime" and result.status == "would_rotate"
    assert (runtime.taints, runtime.removals, runtime.requests) == (0, 0, 0)


def test_downtime_mode_resumes_taint_without_repeating_it(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.tainted = True
    result = rotation.rotate(
        request(mode="with-downtime", dry_run=False, expected_key_id=OLD),
        target,
        runtime,
    )
    assert result.status == "requested"
    assert (runtime.taints, runtime.removals, runtime.requests) == (0, 0, 1)


def test_cannot_switch_to_downtime_mode_after_state_removal(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = None
    with pytest.raises(rotation.RotationError, match="instead of switching"):
        rotation.rotate(
            request(mode="with-downtime", dry_run=False, expected_key_id=OLD),
            target,
            runtime,
        )
    assert (runtime.taints, runtime.removals, runtime.requests) == (0, 0, 0)


@pytest.mark.parametrize("old_present", [True, False])
def test_downtime_verification_requires_old_key_absent(
    target: rotation.Target, runtime: Mock, old_present: bool
) -> None:
    runtime.state.key_id = NEW
    runtime.keys = [rotation.IamKey(AccessKeyId=NEW, Status="Active")]
    if old_present:
        runtime.keys.append(rotation.IamKey(AccessKeyId=OLD, Status="Active"))
    result = rotation.rotate(
        request(mode="with-downtime", verify=True, expected_key_id=OLD), target, runtime
    )
    assert result.status == ("pending" if old_present else "replaced")
    assert (runtime.taints, runtime.removals, runtime.requests) == (0, 0, 0)


@pytest.mark.parametrize("mode", ["with-downtime", "without-downtime"])
@pytest.mark.parametrize("verify", [True, False])
def test_native_cli_forwards_rotation_mode(
    cli_setup: Mock, mocker: MockerFixture, mode: str, verify: bool
) -> None:
    run = mocker.patch.object(rotation, "run_single", return_value=result("pending"))
    response = CliRunner().invoke(
        qontract_cli.external_resources,
        [
            *cli_args(),
            "--mode",
            mode,
            "--verify" if verify else "--no-dry-run",
            "--expected-key-id",
            OLD,
        ],
        obj={},
    )
    assert response.exit_code == 2, response.output
    assert run.call_args.kwargs["mode"] == mode
    assert run.call_args.kwargs["verify"] == verify


def test_native_cli_rejects_unknown_rotation_mode(
    cli_setup: Mock, mocker: MockerFixture
) -> None:
    run = mocker.patch.object(rotation, "run_single")
    response = CliRunner().invoke(
        qontract_cli.external_resources, [*cli_args(), "--mode", "automatic"], obj={}
    )
    assert response.exit_code == 2
    run.assert_not_called()


@pytest.mark.parametrize("changed", [False, True])
def test_container_taints_only_expected_managed_key(
    tmp_path: Path,
    terraform_state: rotation.TerraformState,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    changed: bool,
) -> None:
    source = tmp_path / "module"
    source.mkdir()
    monkeypatch.setenv("TERRAFORM_MODULE_SRC_DIR", str(source))
    monkeypatch.setenv("TERRAFORM_MODULE_WORK_DIR", str(tmp_path / "work"))
    before = terraform_state.model_copy(deep=True)
    if changed:
        before.resources[0].instances[0].attributes["id"] = NEW
    terraform_state.resources[0].instances[0].status = "tainted"
    commands = mocker.patch.object(
        rotation,
        "checked",
        side_effect=[
            "",
            "",
            before.model_dump_json(),
            "",
            terraform_state.model_dump_json(),
        ],
    )
    if changed:
        with pytest.raises(rotation.RotationError, match="Remote key changed"):
            rotation.container_operation("taint", "test-cw", OLD)
        assert not any("taint" in call.args[0] for call in commands.call_args_list)
    else:
        result = rotation.container_operation("taint", "test-cw", OLD)
        assert result.key_id == OLD and result.tainted
        assert commands.call_args_list[3].args[0][2:] == [
            "taint",
            "-lock-timeout=60s",
            "aws_iam_access_key.this",
        ]
        assert not any("rm" in call.args[0] for call in commands.call_args_list)


def test_requested_result_round_trips_when_no_key_is_currently_managed(
    target: rotation.Target, runtime: Mock
) -> None:
    result = rotation.rotate(
        request(dry_run=False, expected_key_id=OLD), target, runtime
    )
    assert (
        rotation.Result.model_validate_json(result.model_dump_json(exclude_none=True))
        == result
    )


def test_container_refuses_to_remove_a_tainted_key(
    tmp_path: Path,
    terraform_state: rotation.TerraformState,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    terraform_state.resources[0].instances[0].status = "tainted"
    source = tmp_path / "module"
    source.mkdir()
    monkeypatch.setenv("TERRAFORM_MODULE_SRC_DIR", str(source))
    monkeypatch.setenv("TERRAFORM_MODULE_WORK_DIR", str(tmp_path / "work"))
    commands = mocker.patch.object(
        rotation, "checked", side_effect=["", "", terraform_state.model_dump_json()]
    )
    with pytest.raises(rotation.RotationError, match="already tainted"):
        rotation.container_operation("remove", "test-cw", OLD)
    assert not any("rm" in call.args[0] for call in commands.call_args_list)


def test_state_metadata_rejects_unexpected_additional_key_resources(
    terraform_state: rotation.TerraformState,
) -> None:
    terraform_state.resources.append(
        terraform_state.resources[0].model_copy(update={"name": "unexpected"})
    )
    with pytest.raises(rotation.RotationError, match="exactly one root"):
        rotation.state_metadata(terraform_state, "test-cw")
