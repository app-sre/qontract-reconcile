from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Literal

import pytest
from click.testing import CliRunner

from reconcile.gql_definitions.external_resources import aws_account_identities
from tools import qontract_cli
from tools import rotate_erv2_cloudwatch_keys as rotation

if TYPE_CHECKING:
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
    runtime.state = rotation.KeyState(key_id=OLD, user="test-cw", tainted=False)
    runtime.keys = [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    runtime.er_status = "CREATED"
    runtime.taints = 0
    runtime.requests = 0
    runtime.fail_taint = False
    runtime.lose_request_response = False

    def operation(
        target: rotation.Target,
        action: Literal["inspect", "taint"],
        expected_key: str | None = None,
    ) -> rotation.KeyState:
        if action == "taint":
            assert expected_key == runtime.state.key_id
            runtime.taints += 1
            runtime.state.tainted = True
            if runtime.fail_taint:
                raise rotation.RotationError("simulated interrupted taint")
        return runtime.state.model_copy()

    def request(target: rotation.Target) -> None:
        runtime.requests += 1
        runtime.er_status = "RECONCILIATION_REQUESTED"
        if runtime.lose_request_response:
            raise rotation.RotationError("simulated lost response")

    runtime.operation.side_effect = operation
    runtime.request.side_effect = request
    runtime.iam_keys.side_effect = lambda _: runtime.keys
    runtime.status.side_effect = lambda _: runtime.er_status
    return runtime


def request(**kwargs: str | bool | None) -> rotation.Request:
    return rotation.Request(account="test-account", identifier="test-cw", **kwargs)


def test_inspection_has_no_mutations(target: rotation.Target, runtime: Mock) -> None:
    result = rotation.rotate(request(), target, runtime)
    assert (runtime.taints, runtime.requests) == (0, 0)
    assert result.status == "would_rotate"
    assert result.access_key_id == OLD
    assert result.exit_code == 0


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


def test_execution_taints_only_old_key_and_requests_reconciliation(
    target: rotation.Target, runtime: Mock
) -> None:
    result = rotation.rotate(
        request(dry_run=False, expected_key_id=OLD), target, runtime
    )
    assert result.status == "requested"
    assert (runtime.taints, runtime.requests) == (1, 1)
    runtime.operation.assert_any_call(target, "taint", OLD)


def test_repeat_call_while_pending_does_not_retaint(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    rotation.rotate(command, target, runtime)
    result = rotation.rotate(command, target, runtime)
    assert result.status == "pending"
    assert result.exit_code == 2
    assert (runtime.taints, runtime.requests) == (1, 1)


def test_stale_expected_key_cannot_rotate_replacement(
    target: rotation.Target, runtime: Mock
) -> None:
    runtime.state.key_id = NEW
    result = rotation.rotate(
        request(dry_run=False, expected_key_id=OLD), target, runtime
    )
    assert result.status == "key_changed"
    assert result.exit_code == 2
    assert (runtime.taints, runtime.requests) == (0, 0)


def test_interrupted_taint_resumes_same_old_key_without_retaint(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    runtime.fail_taint = True
    with pytest.raises(rotation.RotationError, match="interrupted taint"):
        rotation.rotate(command, target, runtime)
    result = rotation.rotate(command, target, runtime)
    assert result.status == "requested"
    assert (runtime.taints, runtime.requests) == (1, 1)


def test_lost_request_response_does_not_repeat_rotation(
    target: rotation.Target, runtime: Mock
) -> None:
    command = request(dry_run=False, expected_key_id=OLD)
    runtime.lose_request_response = True
    with pytest.raises(rotation.RotationError, match="lost response"):
        rotation.rotate(command, target, runtime)
    assert rotation.rotate(command, target, runtime).status == "pending"
    assert (runtime.taints, runtime.requests) == (1, 1)


@pytest.mark.parametrize("status", ["ERROR", "NOT_EXISTS", "DELETE_IN_PROGRESS"])
def test_failed_or_deleted_resource_stops_execution(
    target: rotation.Target, runtime: Mock, status: str
) -> None:
    runtime.er_status = status
    with pytest.raises(rotation.RotationError, match="investigate"):
        rotation.rotate(request(dry_run=False, expected_key_id=OLD), target, runtime)
    assert (runtime.taints, runtime.requests) == (0, 0)


@pytest.mark.parametrize(
    ("old_present", "active", "tainted", "status", "expected"),
    [
        (True, True, False, "CREATED", "pending"),
        (False, False, False, "CREATED", "pending"),
        (False, True, False, "PENDING_SECRET_SYNC", "pending"),
        (False, True, True, "CREATED", "pending"),
        (False, True, False, "CREATED", "replaced"),
    ],
)
def test_verification_requires_active_replacement_old_key_removal_and_sync(
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
    assert (runtime.taints, runtime.requests) == (0, 0)


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


def test_container_refuses_to_taint_changed_key(
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
        rotation.container_operation("taint", "test-cw", OLD)
    assert not any("taint" in call.args[0] for call in commands.call_args_list)


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


@pytest.mark.parametrize("verify", [False, True])
def test_reports_other_active_keys_without_rotating_them(
    target: rotation.Target, runtime: Mock, verify: bool
) -> None:
    extra = "AKIA" + "C" * 16
    managed = NEW if verify else OLD
    runtime.state.key_id = managed
    runtime.keys = [
        rotation.IamKey(AccessKeyId=managed, Status="Active"),
        rotation.IamKey(AccessKeyId=extra, Status="Active"),
        rotation.IamKey(AccessKeyId="AKIA" + "D" * 16, Status="Inactive"),
    ]
    result = rotation.rotate(
        rotation.Request(
            account=target.account,
            identifier=target.identifier,
            verify=verify,
            expected_key_id=OLD if verify else None,
        ),
        target,
        runtime,
    )

    assert result.status == ("replaced" if verify else "would_rotate")
    assert result.additional_active_key_ids == [extra]
    assert all(call.args[1] == "inspect" for call in runtime.operation.call_args_list)
    runtime.request.assert_not_called()
