from __future__ import annotations

import io
import json
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner

from reconcile.utils.early_exit_cache import CacheKey
from tools import qontract_cli
from tools import rotate_terraform_resources_keys as rotation

if TYPE_CHECKING:
    from collections.abc import Generator
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
    r.lock.side_effect = nullcontext
    r.target, _ = rotation.resolve_target(request(), inventory)
    r.cache_bucket = "test-cache"
    r.key_last_used.return_value = rotation.IamKeyLastUsed()
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
    assert result.iam_keys == [
        rotation.IamKeyDetails(
            access_key_id=OLD,
            status="Active",
            matches_terraform_binding=True,
            last_used=rotation.IamKeyLastUsed(),
        )
    ]
    assert "test-only-secret" not in result.model_dump_json()
    assert (
        not result.source_secret_sync_verified and result.consumer_verification_required
    )
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_full_slots_identify_extra_key_and_usage(runtime: Mock, dry_run: bool) -> None:
    runtime.current.keys.append(rotation.IamKey(AccessKeyId=NEW, Status="Inactive"))
    runtime.key_last_used.side_effect = [
        None,
        rotation.IamKeyLastUsed.model_validate({
            "LastUsedDate": "2023-03-01T01:02:03Z",
            "ServiceName": "s3",
            "Region": "us-east-1",
        }),
    ]
    command = request() if dry_run else execute()
    with pytest.raises(rotation.RotationError, match="Both IAM key slots") as exc:
        rotation.rotate(command, runtime)
    message = str(exc.value)
    assert (
        f"{OLD}: Active, matches Terraform binding, last-used lookup unavailable"
        in message
    )
    assert (
        f"{NEW}: Inactive, does not match Terraform binding, last used 2023-03-01"
        in message
    )
    assert "service s3, region us-east-1" in message
    assert "delete-access-key" in message
    runtime.remove.assert_not_called()
    runtime.invalidate.assert_not_called()


def test_execution_preserves_old_key_and_invalidates_account_and_unscoped_caches(
    runtime: Mock,
) -> None:
    result = rotation.rotate(execute(), runtime)
    assert result.status == "requested" and result.retained_key_id == OLD
    assert result.access_key_id is None
    assert runtime.current.keys == [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    runtime.remove.assert_called_once()
    assert [str(call.args[0]) for call in runtime.invalidate.call_args_list] == [
        "terraform-resources/0.5.5/no-dry-run/test-account/latest",
        "terraform-resources/0.5.5/no-dry-run/latest",
    ]


def test_unscoped_preparation_cache_matches_the_integration_key(runtime: Mock) -> None:
    unscoped = CacheKey(
        integration="terraform-resources",
        integration_version="0.5.5",
        dry_run=False,
        cache_source={"configuration": "unchanged"},
        shard="",
    ).cache_key_with_digest
    account = unscoped.model_copy(update={"shard": "test-account"})
    unrelated = unscoped.model_copy(update={"shard": "another-account"})
    dry_run = unscoped.model_copy(update={"dry_run": True})
    cached = {str(k) for k in [unscoped, account, unrelated, dry_run]}
    runtime.invalidate.side_effect = lambda key: cached.discard(str(key))

    rotation.rotate(execute(), runtime)

    assert cached == {str(unrelated), str(dry_run)}


def test_failed_unscoped_cache_invalidation_can_resume(runtime: Mock) -> None:
    runtime.invalidate.side_effect = [None, rotation.RotationError("cache failed")]
    with pytest.raises(rotation.RotationError, match="cache failed"):
        rotation.rotate(execute(), runtime)
    runtime.invalidate.side_effect = None
    assert rotation.rotate(execute(), runtime).status == "requested"
    runtime.remove.assert_called_once()


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


def test_cli_forwards_expected_state_guards_without_a_confirmation_flag(
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
    assert not forwarded.dry_run
    assert (
        forwarded.expected_key_id,
        forwarded.expected_address,
        forwarded.expected_cache_bucket,
    ) == (OLD, ADDRESS, "test-cache")
    assert run.call_args.args[2] == "/test/terraform/1.6.6"


@pytest.mark.parametrize("dry_run", [True, False])
def test_preparation_allows_account_disabled_by_rotation_sop(
    inventory: rotation.data.TerraformResourcesIAMKeyRotationQueryData,
    runtime: Mock,
    dry_run: bool,
) -> None:
    assert inventory.accounts
    inventory.accounts[0].disable = rotation.data.DisableClusterAutomationsV1(
        integrations=["terraform-resources", "aws-iam-keys"]
    )
    command = request() if dry_run else execute()
    runtime.target, _ = rotation.resolve_target(command, inventory)
    assert rotation.rotate(command, runtime).status == (
        "would_prepare" if dry_run else "requested"
    )


def test_verification_requires_reenabled_terraform_resources(
    inventory: rotation.data.TerraformResourcesIAMKeyRotationQueryData,
) -> None:
    assert inventory.accounts
    inventory.accounts[0].disable = rotation.data.DisableClusterAutomationsV1(
        integrations=["terraform-resources", "aws-iam-keys"]
    )
    command = request(verify=True, expected_key_id=OLD, expected_address=ADDRESS)
    with pytest.raises(rotation.RotationError, match="Re-enable terraform-resources"):
        rotation.resolve_target(command, inventory)
    inventory.accounts[0].disable.integrations = ["aws-iam-keys"]
    target, _ = rotation.resolve_target(command, inventory)
    assert target.iam_user == "example"


def test_removed_confirmation_flag_is_absent_from_cli_help() -> None:
    response = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources, ["rotate-access-key", "--help"]
    )
    assert response.exit_code == 0
    assert "--account-quiesced" not in response.output
    assert "docs/terraform-resources-key-rotation.md" in response.output


def retirement_request(
    action: str = "deactivate", **options: bool | str
) -> rotation.RetirementRequest:
    return rotation.RetirementRequest(
        account="test-account",
        iam_user="example",
        action=action,
        key_id=OLD,
        **options,
    )


@pytest.fixture
def retirement_runtime(mocker: MockerFixture) -> Mock:
    r = mocker.Mock(spec=rotation.RetirementRuntime)
    r.lock.side_effect = nullcontext
    r.close = mocker.Mock()
    r.key_last_used.return_value = rotation.IamKeyLastUsed()
    r.target = rotation.RetirementTarget(
        account="test-account",
        account_id="111122223333",
        iam_user="example",
        region="us-east-1",
    )
    r.current = [
        rotation.IamKey(AccessKeyId=NEW, Status="Active"),
        rotation.IamKey(AccessKeyId=OLD, Status="Active"),
    ]
    r.keys.side_effect = lambda: [key.model_copy(deep=True) for key in r.current]

    def deactivate(key_id: str) -> None:
        assert key_id == OLD
        next(k for k in r.current if k.access_key_id == key_id).status = "Inactive"

    def delete(key_id: str) -> None:
        assert key_id == OLD
        r.current = [key for key in r.current if key.access_key_id != key_id]

    r.deactivate.side_effect = deactivate
    r.delete.side_effect = delete
    return r


@pytest.mark.parametrize("dry_run", [True, False])
def test_delete_command_handles_active_key_in_one_operation(
    retirement_runtime: Mock, dry_run: bool
) -> None:
    r = retirement_runtime
    result = rotation.retire(retirement_request("delete", dry_run=dry_run), r)
    assert result.key_id == OLD
    assert result.remaining_active_key_ids == [NEW]
    assert result.consumer_verification_required
    assert {key.access_key_id for key in result.iam_keys_before} == {OLD, NEW}
    assert all(key.status == "Active" for key in result.iam_keys_before)
    assert all(key.matches_terraform_binding is None for key in result.iam_keys_before)
    assert all(
        key.last_used == rotation.IamKeyLastUsed() for key in result.iam_keys_before
    )
    assert [c[0] for c in r.method_calls if c[0] in {"key_last_used", "delete"}] == (
        ["key_last_used", "key_last_used"]
        if dry_run
        else ["key_last_used", "key_last_used", "delete"]
    )
    if dry_run:
        assert result.status == "would_deactivate_and_delete"
        assert result.available_key_slots == 0
        r.delete.assert_not_called()
        r.deactivate.assert_not_called()
    else:
        assert result.status == "deleted" and result.available_key_slots == 1
        r.deactivate.assert_called_once_with(OLD)
        r.delete.assert_called_once_with(OLD)
        mutations = [c[0] for c in r.method_calls if c[0] in {"deactivate", "delete"}]
        assert mutations == ["deactivate", "delete"]
        assert r.current == [rotation.IamKey(AccessKeyId=NEW, Status="Active")]


def test_separate_deactivation_and_inactive_key_deletion(
    retirement_runtime: Mock,
) -> None:
    r = retirement_runtime
    assert rotation.retire(retirement_request(), r).status == "would_deactivate"
    r.deactivate.assert_not_called()
    inactive = rotation.retire(retirement_request(dry_run=False), r)
    assert inactive.status == "inactive" and inactive.available_key_slots == 0
    assert (
        rotation.retire(retirement_request(dry_run=False), r).status
        == "already_inactive"
    )
    assert rotation.retire(retirement_request("delete"), r).status == "would_delete"
    r.delete.assert_not_called()
    deleted = rotation.retire(retirement_request("delete", dry_run=False), r)
    assert deleted.status == "deleted" and deleted.available_key_slots == 1
    assert (
        rotation.retire(retirement_request("delete", dry_run=False), r).status
        == "already_deleted"
    )
    r.deactivate.assert_called_once_with(OLD)
    r.delete.assert_called_once_with(OLD)


@pytest.mark.parametrize("selected", ["Active", "Inactive", "absent"])
@pytest.mark.parametrize("other", ["Inactive", "absent"])
@pytest.mark.parametrize("action", ["deactivate", "delete"])
def test_retirement_requires_another_active_key(
    retirement_runtime: Mock, selected: str, other: str, action: str
) -> None:
    r = retirement_runtime
    r.current = [
        rotation.IamKey(AccessKeyId=key_id, Status=status)
        for key_id, status in [(OLD, selected), (NEW, other)]
        if status != "absent"
    ]
    with pytest.raises(rotation.RotationError, match="Another Active key"):
        rotation.retire(retirement_request(action, dry_run=False), r)
    r.deactivate.assert_not_called()
    r.delete.assert_not_called()


@pytest.mark.parametrize("phase", ["preflight", "deactivated", "deleted"])
def test_retirement_rechecks_other_active_key(
    retirement_runtime: Mock, phase: str
) -> None:
    r = retirement_runtime
    if phase == "preflight":
        before = r.keys()
        r.keys.side_effect = [
            before,
            [rotation.IamKey(AccessKeyId=OLD, Status="Active")],
        ]
    else:
        mutation = r.deactivate if phase == "deactivated" else r.delete
        original = mutation.side_effect

        def lose_other_key(key_id: str) -> None:
            original(key_id)
            r.current[0].status = "Inactive"

        mutation.side_effect = lose_other_key
    with pytest.raises(rotation.RotationError, match="Another Active key"):
        rotation.retire(retirement_request("delete", dry_run=False), r)
    if phase == "preflight":
        r.deactivate.assert_not_called()
    if phase != "deleted":
        r.delete.assert_not_called()


def test_retirement_refuses_preflight_key_drift(retirement_runtime: Mock) -> None:
    r = retirement_runtime
    before = r.keys()
    changed = [key.model_copy(deep=True) for key in before]
    changed[1].status = "Inactive"
    r.keys.side_effect = [before, changed]
    with pytest.raises(rotation.RotationError, match="changed during"):
        rotation.retire(retirement_request("delete", dry_run=False), r)
    r.deactivate.assert_not_called()
    r.delete.assert_not_called()


@pytest.mark.parametrize("action", ["deactivate", "delete"])
def test_retirement_verifies_sdk_mutation(
    retirement_runtime: Mock, action: str
) -> None:
    r = retirement_runtime
    if action == "delete":
        r.current[1].status = "Inactive"
    mutation = r.deactivate if action == "deactivate" else r.delete
    mutation.side_effect = None
    with pytest.raises(rotation.RotationError, match="did not reach the expected"):
        rotation.retire(retirement_request(action, dry_run=False), r)
    if action == "deactivate":
        r.delete.assert_not_called()


def test_combined_delete_waits_for_inactive_confirmation(
    retirement_runtime: Mock,
) -> None:
    retirement_runtime.deactivate.side_effect = None
    with pytest.raises(rotation.RotationError, match="expected Inactive"):
        rotation.retire(retirement_request("delete", dry_run=False), retirement_runtime)
    retirement_runtime.delete.assert_not_called()


def test_overlapping_retirements_cannot_deactivate_both_keys(
    retirement_runtime: Mock,
) -> None:
    r = retirement_runtime
    held = False

    @contextmanager
    def lock() -> Generator[None]:
        nonlocal held
        if held:
            raise rotation.RotationError("another retirement holds the lock")
        held = True
        try:
            yield
        finally:
            held = False

    r.lock.side_effect = lock
    original = r.deactivate.side_effect

    def overlap(key_id: str) -> None:
        reads = r.keys.call_count
        other = retirement_request("delete", dry_run=False).model_copy(
            update={"key_id": NEW}
        )
        with pytest.raises(rotation.RotationError, match="another retirement"):
            rotation.retire(other, r)
        assert r.keys.call_count == reads
        original(key_id)

    r.deactivate.side_effect = overlap
    assert (
        rotation.retire(retirement_request("delete", dry_run=False), r).status
        == "deleted"
    )
    assert r.current == [rotation.IamKey(AccessKeyId=NEW, Status="Active")]
    assert not held


@pytest.mark.parametrize("phase", ["deactivate", "delete"])
def test_combined_delete_recovers_after_lost_response(
    retirement_runtime: Mock, phase: str
) -> None:
    r = retirement_runtime
    mutation = getattr(r, phase)
    original = mutation.side_effect

    def lost_response(key_id: str) -> None:
        original(key_id)
        raise rotation.RotationError("simulated lost response")

    mutation.side_effect = lost_response
    command = retirement_request("delete", dry_run=False)
    with pytest.raises(rotation.RotationError, match="lost response"):
        rotation.retire(command, r)
    assert rotation.retire(command, r).status == (
        "deleted" if phase == "deactivate" else "already_deleted"
    )
    r.deactivate.assert_called_once_with(OLD)
    r.delete.assert_called_once_with(OLD)


def test_retirement_rejects_target_mismatch(retirement_runtime: Mock) -> None:
    retirement_runtime.target.iam_user = "other"
    with pytest.raises(rotation.RotationError, match="Resolved target"):
        rotation.retire(retirement_request(), retirement_runtime)
    retirement_runtime.keys.assert_not_called()


@pytest.mark.parametrize("action", ["deactivate", "delete"])
@pytest.mark.parametrize("execute", [False, True])
def test_retirement_cli_accepts_one_key(
    mocker: MockerFixture, retirement_runtime: Mock, action: str, execute: bool
) -> None:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    reader = mocker.patch.object(qontract_cli, "create_secret_reader")
    run = mocker.patch.object(
        rotation,
        "run_retirement",
        return_value=rotation.retire(retirement_request(action), retirement_runtime),
    )
    response = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources,
        [
            action + "-access-key",
            "--account",
            "test-account",
            "--iam-user",
            "example",
            "--key-id",
            OLD,
        ]
        + (["--no-dry-run"] if execute else []),
    )
    assert response.exit_code == 0, response.output
    command = run.call_args.args[0]
    assert command.action == action and command.dry_run != execute
    assert command.key_id == OLD
    assert run.call_args.args[1] is reader.return_value
    help_result = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources, [action + "-access-key", "--help"]
    )
    assert "--old-key-id" not in help_result.output
    assert "--replacement-key-id" not in help_result.output


def test_retirement_cli_suppresses_credential_bearing_errors(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(qontract_cli, "get_app_interface_vault_settings")
    mocker.patch.object(qontract_cli, "create_secret_reader")
    mocker.patch.object(
        rotation, "run_retirement", side_effect=ValueError("test-only-secret")
    )
    response = CliRunner().invoke(
        qontract_cli.legacy_terraform_resources,
        [
            "delete-access-key",
            "--account",
            "test-account",
            "--iam-user",
            "example",
            "--key-id",
            OLD,
        ],
    )
    assert response.exit_code == 1 and "test-only-secret" not in response.output


@pytest.fixture
def retirement_api(mocker: MockerFixture) -> Mock:
    api = mocker.patch.object(rotation, "AWSApi").return_value
    api.sts.client.get_caller_identity.return_value = {"Account": "111122223333"}
    return api


def test_retirement_client_uses_iam_only_and_exact_user_key(
    retirement_api: Mock,
    retirement_runtime: Mock,
) -> None:
    api = retirement_api
    credentials = rotation.AWSStaticCredentials(
        access_key_id=NEW, secret_access_key="test-only-secret", region="us-east-1"
    )
    client = rotation.RetirementClient(retirement_runtime.target, credentials)
    api.iam.client.list_access_keys.return_value = {
        "AccessKeyMetadata": [{"AccessKeyId": OLD, "Status": "Active"}],
    }
    assert client.keys() == [rotation.IamKey(AccessKeyId=OLD, Status="Active")]
    api.iam.client.list_access_keys.assert_called_once_with(UserName="example")
    client.deactivate(OLD)
    api.iam.client.update_access_key.assert_called_once_with(
        UserName="example", AccessKeyId=OLD, Status="Inactive"
    )
    client.delete(OLD)
    api.iam.client.delete_access_key.assert_called_once_with(
        UserName="example",
        AccessKeyId=OLD,
    )
    client.close()
    api.close.assert_called_once()
    api.s3.client.get_object.assert_not_called()


def test_key_last_used_distinguishes_missing_usage_from_denied_lookup(
    retirement_api: Mock,
) -> None:
    iam = retirement_api.iam.client
    iam.get_access_key_last_used.side_effect = [
        {"AccessKeyLastUsed": {"ServiceName": "N/A", "Region": "N/A"}},
        ClientError({"Error": {"Code": "AccessDenied"}}, "GetAccessKeyLastUsed"),
    ]
    no_usage = rotation.read_key_last_used(iam, OLD)
    assert no_usage is not None and no_usage.date is None
    assert rotation.read_key_last_used(iam, NEW) is None


def test_retirement_client_rejects_pagination(
    retirement_api: Mock,
    retirement_runtime: Mock,
) -> None:
    client = rotation.RetirementClient(
        retirement_runtime.target,
        rotation.AWSStaticCredentials(
            access_key_id=NEW, secret_access_key="test", region="us-east-1"
        ),
    )
    retirement_api.iam.client.list_access_keys.return_value = {"IsTruncated": True}
    with pytest.raises(rotation.RotationError, match="pagination"):
        client.keys()


def test_retirement_client_checks_account_and_closes_on_failure(
    retirement_api: Mock,
    retirement_runtime: Mock,
) -> None:
    retirement_api.sts.client.get_caller_identity.return_value = {
        "Account": "999988887777"
    }
    with pytest.raises(rotation.RotationError, match="caller account"):
        rotation.RetirementClient(
            retirement_runtime.target,
            rotation.AWSStaticCredentials(
                access_key_id=NEW, secret_access_key="test", region="us-east-1"
            ),
        )
    retirement_api.close.assert_called_once()
    retirement_api.iam.client.list_access_keys.assert_not_called()


@pytest.fixture
def retirement_inventory(
    mocker: MockerFixture,
) -> Mock:
    mocker.patch.object(rotation.gql, "get_api")
    return mocker.patch.object(
        rotation.retirement_data,
        "query",
        return_value=rotation.retirement_data.IAMKeyRetirementAccountQueryData.model_validate({
            "accounts": [
                {
                    "name": "test-account",
                    "uid": "111122223333",
                    "resourcesDefaultRegion": "us-east-1",
                    "automationToken": {
                        "url": None,
                        "path": "test/automation",
                        "field": "all",
                        "version": None,
                        "format": None,
                    },
                }
            ]
        }),
    )


def test_run_retirement_needs_no_terraform_or_namespace_data(
    mocker: MockerFixture,
    retirement_inventory: Mock,
    retirement_runtime: Mock,
) -> None:
    legacy_query = mocker.patch.object(rotation.data, "query")
    resolve = mocker.patch.object(rotation, "resolve_target")
    client = mocker.patch.object(
        rotation, "RetirementClient", return_value=retirement_runtime
    )
    reader = mocker.Mock()
    reader.read_all_secret.return_value = {
        "aws_access_key_id": NEW,
        "aws_secret_access_key": "test-only-secret",
    }
    result = rotation.run_retirement(retirement_request("delete"), reader)
    assert result.status == "would_deactivate_and_delete"
    assert retirement_inventory.call_args.kwargs["variables"] == {
        "filter": {"name": "test-account"}
    }
    assert client.call_args.args[0] == retirement_runtime.target
    retirement_runtime.close.assert_called_once()
    legacy_query.assert_not_called()
    resolve.assert_not_called()


def test_run_retirement_closes_client_on_failure(
    mocker: MockerFixture,
    retirement_inventory: Mock,
    retirement_runtime: Mock,
) -> None:
    mocker.patch.object(rotation, "RetirementClient", return_value=retirement_runtime)
    reader = mocker.Mock()
    reader.read_all_secret.return_value = {
        "aws_access_key_id": NEW,
        "aws_secret_access_key": "test-only-secret",
    }
    retirement_runtime.keys.side_effect = rotation.RotationError("read failed")
    with pytest.raises(rotation.RotationError, match="read failed"):
        rotation.run_retirement(retirement_request("delete"), reader)
    retirement_runtime.close.assert_called_once()


def test_run_retirement_refuses_executing_credential(
    mocker: MockerFixture,
    retirement_inventory: Mock,
) -> None:
    client = mocker.patch.object(rotation, "RetirementClient")
    reader = mocker.Mock()
    reader.read_all_secret.return_value = {
        "aws_access_key_id": OLD,
        "aws_secret_access_key": "test-only-secret",
    }
    with pytest.raises(rotation.RotationError, match="executing credential"):
        rotation.run_retirement(retirement_request(), reader)
    client.assert_not_called()


@pytest.mark.parametrize(
    "accounts", [None, [], ["other"], ["test-account", "test-account"]]
)
def test_run_retirement_requires_exact_account(
    mocker: MockerFixture,
    retirement_inventory: Mock,
    accounts: list[str] | None,
) -> None:
    original = retirement_inventory.return_value.accounts[0]
    retirement_inventory.return_value.accounts = (
        [original.model_copy(update={"name": name}) for name in accounts]
        if accounts is not None
        else None
    )
    reader = mocker.Mock()
    with pytest.raises(rotation.RotationError, match="exactly one"):
        rotation.run_retirement(retirement_request(), reader)
    reader.read_all_secret.assert_not_called()
