from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from tools import qontract_cli
from tools import rotate_terraform_resources_keys as rotation

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import Mock

    from pytest_mock import MockerFixture

OLD = "AKIA" + "A" * 16
NEW = "AKIA" + "B" * 16
ADDRESS = "aws_iam_access_key.example"


@pytest.fixture
def inventory() -> rotation.data.TerraformResourcesIAMKeyRotationQueryData:
    return rotation.data.TerraformResourcesIAMKeyRotationQueryData.model_validate({
        "accounts": [
            {
                "name": "test-account",
                "uid": "111122223333",
                "deleteKeys": None,
                "disable": None,
                "automationToken": {
                    "url": None,
                    "path": "test/automation",
                    "field": "all",
                    "version": None,
                    "format": None,
                },
                "terraformState": {
                    "bucket": "test-tf-state",
                    "region": "us-east-1",
                    "integrations": [
                        {
                            "integration": "terraform-resources",
                            "key": "resources.tfstate",
                        }
                    ],
                },
            }
        ],
        "namespaces": [
            {
                "name": "test-ns",
                "delete": False,
                "managedExternalResources": True,
                "cluster": {"name": "test-cluster", "disable": None},
                "externalResources": [
                    {
                        "provider": "aws",
                        "provisioner": {"name": "test-account"},
                        "resources": [
                            {
                                "provider": "s3",
                                "identifier": "example",
                                "output_resource_name": "custom-bucket-secret",
                            }
                        ],
                    }
                ],
            }
        ],
    })


def request(**options: str | bool | None) -> rotation.Request:
    return rotation.Request(
        account="test-account",
        iam_user="example",
        integration_version="0.5.5",
        **options,
    )


def execute(**options: str | bool | None) -> rotation.Request:
    return request(
        dry_run=False,
        expected_key_id=OLD,
        expected_address=ADDRESS,
        expected_cache_bucket="test-cache",
        account_quiesced=True,
        **options,
    )


@pytest.fixture
def state() -> rotation.StateDocument:
    return rotation.StateDocument.model_validate({
        "version": 4,
        "lineage": "test-lineage",
        "serial": 7,
        "terraform_version": "1.6.6",
        "outputs": {
            "example-s3__aws_access_key_id": {
                "value": OLD,
                "sensitive": True,
                "type": "string",
            }
        },
        "resources": [
            {
                "mode": "managed",
                "type": "aws_iam_access_key",
                "name": "example",
                "provider": "provider.aws",
                "instances": [
                    {
                        "schema_version": 0,
                        "attributes": {
                            "id": OLD,
                            "user": "example",
                            "secret": "test-only-secret",
                        },
                        "private": "test-private",
                    }
                ],
            },
            {
                "mode": "managed",
                "type": "aws_s3_bucket",
                "name": "example",
                "instances": [{"attributes": {"id": "example"}}],
            },
        ],
    })


@pytest.fixture
def runtime(
    mocker: MockerFixture,
    inventory: rotation.data.TerraformResourcesIAMKeyRotationQueryData,
    state: rotation.StateDocument,
) -> Mock:
    r = mocker.Mock(spec=rotation.RotationRuntime)
    r.target, _ = rotation.resolve_target(request(), inventory)
    r.cache_bucket = "test-cache"
    r.current = rotation.Snapshot(
        state=state,
        managed_key=rotation.ManagedKey(address=ADDRESS, key_id=OLD),
        keys=[rotation.IamKey(AccessKeyId=OLD, Status="Active")],
        outputs_match=True,
    )
    r.snapshot.side_effect = lambda _: r.current.model_copy(deep=True)

    def remove(before: rotation.Snapshot, address: str) -> None:
        assert before == r.current and address == ADDRESS
        r.current.managed_key = None
        r.current.state.resources = r.current.state.resources[1:]
        r.current.state.serial += 1
        r.current.outputs_match = False

    r.remove.side_effect = remove
    return r


def test_inspection_reports_one_user_and_bindings_without_mutation(
    runtime: Mock,
) -> None:
    result = rotation.rotate(request(), runtime)
    assert result.status == "would_prepare" and result.access_key_id == OLD
    assert result.address == ADDRESS and result.cache_bucket == "test-cache"
    assert result.bindings[0].secret_name == "custom-bucket-secret"
    assert result.terraform_version == "1.6.6"
    assert "test-only-secret" not in result.model_dump_json()
    assert (
        not result.source_secret_sync_verified and result.consumer_verification_required
    )
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


def test_execution_preserves_old_key_and_invalidates_only_account_cache(
    runtime: Mock,
) -> None:
    result = rotation.rotate(execute(), runtime)
    assert result.status == "requested" and result.retained_key_id == OLD
    assert result.access_key_id is None
    assert runtime.current.keys == [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    runtime.remove.assert_called_once()
    key = runtime.invalidate.call_args.args[0]
    assert str(key) == "terraform-resources/0.5.5/no-dry-run/test-account/latest"


def test_resume_after_state_removal_does_not_remove_another_binding(
    runtime: Mock,
) -> None:
    rotation.rotate(execute(), runtime)
    result = rotation.rotate(execute(), runtime)
    assert result.status == "requested" and result.retained_key_id == OLD
    assert runtime.remove.call_count == 1


@pytest.mark.parametrize(
    "options",
    [
        {"dry_run": False},
        {"verify": True, "expected_key_id": OLD},
        {"dry_run": False, "expected_key_id": OLD, "expected_address": ADDRESS},
        {
            "dry_run": False,
            "expected_key_id": OLD,
            "expected_address": ADDRESS,
            "expected_cache_bucket": "test-cache",
        },
        {
            "verify": True,
            "dry_run": False,
            "expected_key_id": OLD,
            "expected_address": ADDRESS,
        },
    ],
)
def test_missing_guards_fail_before_state_reads(
    runtime: Mock, options: dict[str, str | bool]
) -> None:
    with pytest.raises(rotation.RotationError):
        rotation.rotate(request(**options), runtime)
    runtime.snapshot.assert_not_called()


def test_cache_bucket_drift_blocks_mutation(runtime: Mock) -> None:
    runtime.cache_bucket = "different-cache"
    with pytest.raises(rotation.RotationError, match="Cache bucket changed"):
        rotation.rotate(execute(), runtime)
    runtime.remove.assert_not_called()


@pytest.mark.parametrize("status", ["Active", "Inactive"])
def test_second_key_blocks_preparation_without_deleting_it(
    runtime: Mock, status: str
) -> None:
    runtime.current.keys.append(rotation.IamKey(AccessKeyId=NEW, Status=status))
    with pytest.raises(rotation.RotationError, match="exactly one"):
        rotation.rotate(execute(), runtime)
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


def test_stale_expected_key_cannot_rotate_new_managed_key(runtime: Mock) -> None:
    runtime.current.managed_key.key_id = NEW
    assert rotation.rotate(execute(), runtime).status == "key_changed"
    runtime.remove.assert_not_called()


def test_scheduled_delete_keys_retirement_blocks_preserving_old_key(
    runtime: Mock,
) -> None:
    runtime.target.deletion_keys = [OLD]
    with pytest.raises(rotation.RotationError, match="listed in deleteKeys"):
        rotation.rotate(execute(), runtime)
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


@pytest.mark.parametrize(
    ("old_status", "new_status", "outputs_match", "expected"),
    [
        ("Active", "Active", True, "key_created"),
        ("Inactive", "Active", True, "pending"),
        (None, "Active", True, "old_key_retired"),
        ("Active", "Inactive", True, "pending"),
        ("Active", "Active", False, "pending"),
    ],
)
def test_verification_is_explicit_about_iam_outputs_and_unverified_consumers(
    runtime: Mock,
    old_status: str | None,
    new_status: str,
    outputs_match: bool,
    expected: str,
) -> None:
    runtime.current.managed_key.key_id = NEW
    runtime.current.keys = [rotation.IamKey(AccessKeyId=NEW, Status=new_status)]
    if old_status:
        runtime.current.keys.append(rotation.IamKey(AccessKeyId=OLD, Status=old_status))
    runtime.current.outputs_match = outputs_match
    result = rotation.rotate(
        request(verify=True, expected_key_id=OLD, expected_address=ADDRESS), runtime
    )
    assert result.status == expected
    assert (
        not result.source_secret_sync_verified and result.consumer_verification_required
    )
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


@pytest.mark.parametrize(
    "change", ["module", "indexed", "deposed", "tainted", "wrong-user", "duplicate"]
)
def test_unsafe_state_binding_is_rejected(
    state: rotation.StateDocument, change: str
) -> None:
    resource = state.resources[0]
    instance = resource.instances[0]
    if change == "module":
        resource.module = "module.other"
    if change == "indexed":
        instance.index_key = 0
    if change == "deposed":
        instance.deposed = "old"
    if change == "tainted":
        instance.status = "tainted"
    if change == "wrong-user":
        instance.attributes["user"] = "other-user"
    if change == "duplicate":
        state.resources.append(resource.model_copy(deep=True))
    with pytest.raises(rotation.RotationError):
        rotation.select_key(state, "example", ADDRESS)


def test_state_model_preserves_fields_needed_for_full_post_write_comparison(
    state: rotation.StateDocument,
) -> None:
    clone = rotation.StateDocument.model_validate_json(state.model_dump_json())
    assert clone == state
    assert clone.resources[0].__pydantic_extra__ is not None
    assert clone.resources[0].instances[0].__pydantic_extra__ is not None
    assert clone.resources[0].__pydantic_extra__["provider"] == "provider.aws"
    assert (
        clone.resources[0].instances[0].__pydantic_extra__["private"] == "test-private"
    )


@pytest.mark.parametrize("explicit", [True, False])
def test_backend_discovery_matches_legacy_credential_metadata_and_explicit_override(
    inventory: rotation.data.TerraformResourcesIAMKeyRotationQueryData, explicit: bool
) -> None:
    assert inventory.accounts and inventory.accounts[0].terraform_state
    if not explicit:
        inventory.accounts[0].terraform_state.integrations = []
    material = rotation.CredentialMaterial(
        aws_access_key_id="test-key",
        aws_secret_access_key="test-only-secret",
        bucket="credential-backend",
        region="us-west-2",
        terraform_resources_key="legacy.tfstate",
    )
    target, _ = rotation.resolve_target(request(), inventory, material)
    expected = (
        ("test-tf-state", "resources.tfstate", "us-east-1")
        if explicit
        else ("credential-backend", "legacy.tfstate", "us-west-2")
    )
    assert (target.bucket, target.key, target.region) == expected


@pytest.mark.parametrize(
    "change",
    [
        "disabled-account",
        "missing-backend",
        "no-namespaces",
        "deleted",
        "unmanaged",
        "disabled-cluster",
        "erv2",
    ],
)
def test_only_enabled_desired_legacy_resources_are_eligible(
    inventory: rotation.data.TerraformResourcesIAMKeyRotationQueryData, change: str
) -> None:
    assert inventory.accounts and inventory.namespaces
    account = inventory.accounts[0]
    namespace = inventory.namespaces[0]
    assert namespace.external_resources
    spec = namespace.external_resources[0]
    assert isinstance(spec, rotation.data.NamespaceTerraformProviderResourceAWSV1)
    if change == "disabled-account":
        account.disable = rotation.data.DisableClusterAutomationsV1(
            integrations=["terraform-resources"]
        )
    if change == "missing-backend":
        account.terraform_state = None
    if change == "no-namespaces":
        inventory.namespaces = []
    if change == "deleted":
        namespace.delete = True
    if change == "unmanaged":
        namespace.managed_external_resources = False
    if change == "disabled-cluster":
        namespace.cluster.disable = rotation.data.ClusterV1_DisableClusterAutomationsV1(
            integrations=["terraform-resources"]
        )
    if change == "erv2":
        spec.resources = [
            rotation.data.NamespaceTerraformResourceCloudWatchV1(
                provider="cloudwatch",
                identifier="example",
                output_resource_name="cloudwatch",
                managed_by_erv2=True,
            )
        ]
    with pytest.raises(rotation.RotationError):
        rotation.resolve_target(request(), inventory)


def build_runtime(
    mocker: MockerFixture, runtime: Mock, tmp_path: Path
) -> rotation.Runtime:
    r = rotation.Runtime.__new__(rotation.Runtime)
    r.target = runtime.target
    r.credentials = rotation.AWSStaticCredentials(
        access_key_id="test-key",
        secret_access_key="test-only-secret",
        region="us-east-1",
    )
    r.directory = tmp_path
    r.terraform_binary = "terraform"
    mocker.patch.object(rotation.shutil, "which", return_value="/test/bin/terraform")
    return r


def test_wrong_terraform_version_stops_before_init_or_state_mutation(
    mocker: MockerFixture, runtime: Mock, tmp_path: Path
) -> None:
    r = build_runtime(mocker, runtime, tmp_path)
    command = mocker.patch.object(
        rotation, "checked", return_value=json.dumps({"terraform_version": "1.13.4"})
    )
    with pytest.raises(rotation.RotationError, match="exactly match"):
        r.remove(runtime.current, ADDRESS)
    assert command.call_count == 1


@pytest.mark.parametrize("concurrent_change", ["none", "before", "after"])
def test_state_removal_checks_exact_scope_and_complete_state_before_write(
    mocker: MockerFixture, runtime: Mock, tmp_path: Path, concurrent_change: str
) -> None:
    r = build_runtime(mocker, runtime, tmp_path)
    before = runtime.current.model_copy(deep=True)
    after = before.model_copy(deep=True)
    after.managed_key = None
    after.state.resources = after.state.resources[1:]
    after.state.serial += 1
    after.outputs_match = False
    fresh = before.model_copy(deep=True)
    if concurrent_change == "before":
        fresh.state.serial += 1
    if concurrent_change == "after":
        after.state.resources[0].instances[0].attributes["id"] = "unexpected-change"
    mocker.patch.object(r, "snapshot", side_effect=[fresh, after])
    command = mocker.patch.object(
        rotation,
        "checked",
        side_effect=[
            json.dumps({"terraform_version": "1.6.6"}),
            "",
            "Would remove " + ADDRESS + "\n",
            "",
        ],
    )
    if concurrent_change == "before":
        with pytest.raises(rotation.RotationError, match="changed during preflight"):
            r.remove(before, ADDRESS)
        assert command.call_count == 3
    elif concurrent_change == "after":
        with pytest.raises(rotation.RotationError, match="exact expected change"):
            r.remove(before, ADDRESS)
    else:
        r.remove(before, ADDRESS)
        assert command.call_args.args[0][2:] == [
            "state",
            "rm",
            "-lock-timeout=180s",
            ADDRESS,
        ]
        assert all(
            "apply" not in c.args[0] and "taint" not in c.args[0]
            for c in command.call_args_list
        )
        assert "test-only-secret" not in (tmp_path / "backend.tf.json").read_text()


@pytest.mark.parametrize("verify", [False, True])
def test_cli_forwards_single_resource_parameters(
    mocker: MockerFixture, runtime: Mock, verify: bool
) -> None:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    reader = mocker.patch.object(qontract_cli, "create_secret_reader")
    output = rotation.rotate(request(), runtime)
    run = mocker.patch.object(rotation, "run_single", return_value=output)
    args = [
        "rotate-access-key",
        "--account",
        "test-account",
        "--iam-user",
        "example",
        "--expected-key-id",
        OLD,
        "--expected-address",
        ADDRESS,
    ]
    if verify:
        args.append("--verify")
    response = CliRunner().invoke(qontract_cli.legacy_terraform_resources, args)
    assert response.exit_code == 0, response.output
    forwarded = run.call_args.args[0]
    assert (forwarded.account, forwarded.iam_user, forwarded.verify) == (
        "test-account",
        "example",
        verify,
    )
    assert run.call_args.args[1] is reader.return_value


def test_cli_hides_credential_bearing_exceptions(mocker: MockerFixture) -> None:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    mocker.patch.object(qontract_cli, "create_secret_reader")
    mocker.patch.object(
        rotation, "run_single", side_effect=ValueError("test-only-secret")
    )
    response = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources,
        ["rotate-access-key", "--account", "test-account", "--iam-user", "example"],
    )
    assert response.exit_code == 1
    assert "test-only-secret" not in response.output


@pytest.mark.parametrize(
    "identity",
    [
        {"Account": "444455556666", "Arn": "arn:aws:iam::444455556666:user/automation"},
        {"Account": "111122223333", "Arn": "arn:aws:iam::111122223333:user/example"},
    ],
)
def test_wrong_or_self_rotating_aws_identity_stops_before_state_or_cache_access(
    mocker: MockerFixture, runtime: Mock, identity: dict[str, str]
) -> None:
    api = mocker.patch.object(rotation, "AWSApi").return_value
    api.sts.client.get_caller_identity.return_value = identity
    cache = mocker.patch.object(rotation.EarlyExitCache, "build")
    credentials = rotation.AWSStaticCredentials(
        access_key_id="test-key",
        secret_access_key="test-only-secret",
        region="us-east-1",
    )
    with pytest.raises(rotation.RotationError, match="Wrong AWS identity"):
        rotation.Runtime(runtime.target, credentials, mocker.Mock(), "terraform", False)
    api.s3.client.get_object.assert_not_called()
    cache.assert_not_called()
    api.close.assert_called_once()


def test_snapshot_verifies_every_terraform_output_and_excludes_state_from_serialization(
    mocker: MockerFixture,
    runtime: Mock,
    state: rotation.StateDocument,
) -> None:
    r = rotation.Runtime.__new__(rotation.Runtime)
    r.target = runtime.target
    api = mocker.Mock()
    r.api = api
    body = io.BytesIO(state.model_dump_json().encode())
    api.s3.client.get_object.return_value = {"Body": body}
    api.iam.client.list_access_keys.return_value = {
        "AccessKeyMetadata": [{"AccessKeyId": OLD, "Status": "Active"}]
    }
    result = r.snapshot(ADDRESS)
    assert result.outputs_match and body.closed
    assert "test-only-secret" not in result.model_dump_json()
    api.iam.client.delete_access_key.assert_not_called()
    api.iam.client.update_access_key.assert_not_called()


def test_invalid_request_stops_before_querying_or_reading_credentials(
    mocker: MockerFixture,
) -> None:
    query = mocker.patch.object(rotation.data, "query")
    with pytest.raises(rotation.RotationError, match="--expected-key-id"):
        rotation.run_single(request(dry_run=False), mocker.Mock())
    query.assert_not_called()


@pytest.mark.parametrize("exists", [False, True])
def test_cache_invalidation_uses_only_exact_supplied_key(
    mocker: MockerFixture, exists: bool
) -> None:
    r = rotation.Runtime.__new__(rotation.Runtime)
    cache = mocker.Mock()
    r.cache = cache
    cache.state.head.return_value = (exists, {})
    key = rotation.CacheKeyWithDigest(
        integration="terraform-resources",
        integration_version="0.5.5",
        dry_run=False,
        cache_source_digest="",
        shard="test-account",
    )
    r.invalidate(key)
    cache.state.head.assert_called_once_with(str(key))
    if exists:
        cache.delete.assert_called_once_with(key)
    else:
        cache.delete.assert_not_called()


def test_cli_forwards_quiescence_and_expected_state_guards(
    mocker: MockerFixture, runtime: Mock
) -> None:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    mocker.patch.object(qontract_cli, "create_secret_reader")
    run = mocker.patch.object(
        rotation, "run_single", return_value=rotation.rotate(request(), runtime)
    )
    response = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources,
        [
            "rotate-access-key",
            "--account",
            "test-account",
            "--iam-user",
            "example",
            "--no-dry-run",
            "--account-quiesced",
            "--expected-key-id",
            OLD,
            "--expected-address",
            ADDRESS,
            "--expected-cache-bucket",
            "test-cache",
            "--terraform-binary",
            "/test/terraform/1.6.6",
        ],
    )
    assert response.exit_code == 0, response.output
    forwarded = run.call_args.args[0]
    assert not forwarded.dry_run and forwarded.account_quiesced
    assert (
        forwarded.expected_key_id,
        forwarded.expected_address,
        forwarded.expected_cache_bucket,
    ) == (OLD, ADDRESS, "test-cache")
    assert run.call_args.args[2] == "/test/terraform/1.6.6"
