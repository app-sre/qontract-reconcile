"""Prepare one legacy terraform-resources IAM key without retiring the old key.

Inspection is the default. Execution forgets exactly one verified IAM key binding
and invalidates only the account's terraform-resources early-exit cache. Normal
reconciliation creates the new key and publishes outputs. Verification checks
IAM and Terraform outputs only; source Secrets and application adoption require
separate verification before the operator retires the old key. No apply, taint,
IAM key deletion, or application refresh is performed by this tool.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from qontract_utils.aws_api_typed.api import (
    AWSApi,
    AWSStaticCredentials,
    AWSTemporaryCredentials,
)

from reconcile.gql_definitions.terraform_resources import iam_key_rotation as data
from reconcile.utils import gql
from reconcile.utils.early_exit_cache import CacheKeyWithDigest, EarlyExitCache
from tools.rotate_erv2_cloudwatch_keys import (
    IamKey,
    IamStateAttributes,
    RotationError,
    TerraformInstance,
    checked,
)

if TYPE_CHECKING:
    from reconcile.utils.secret_reader import SecretReaderBase


KEY_PATTERN = r"^AKIA[A-Z0-9]{16}$"
ADDRESS_PATTERN = r"^aws_iam_access_key\.[A-Za-z_][A-Za-z0-9_-]*$"
RESOURCE_TYPES = (
    data.NamespaceTerraformResourceS3V1,
    data.NamespaceTerraformResourceS3CloudFrontV1,
    data.NamespaceTerraformResourceServiceAccountV1,
    data.NamespaceTerraformResourceSecretsManagerServiceAccountV1,
    data.NamespaceTerraformResourceSQSV1,
    data.NamespaceTerraformResourceDynamoDBV1,
    data.NamespaceTerraformResourceECRV1,
    data.NamespaceTerraformResourceKinesisV1,
    data.NamespaceTerraformResourceRoute53ZoneV1,
    data.NamespaceTerraformResourceCloudWatchV1,
)
RotationStatus = Literal[
    "would_prepare",
    "requested",
    "pending",
    "key_created",
    "old_key_retired",
    "key_changed",
]


class Request(BaseModel):
    account: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    iam_user: str = Field(pattern=r"^[\w+=,.@-]+$")
    dry_run: bool = True
    verify: bool = False
    expected_key_id: str | None = Field(default=None, pattern=KEY_PATTERN)
    expected_address: str | None = Field(default=None, pattern=ADDRESS_PATTERN)
    expected_cache_bucket: str | None = None
    account_quiesced: bool = False
    integration_version: str


class Binding(BaseModel):
    cluster: str
    namespace: str
    provider: str
    secret_name: str
    output_key: str


class Target(BaseModel):
    account: str
    account_id: str = Field(pattern=r"^\d{12}$")
    iam_user: str
    bucket: str
    key: str
    region: str
    bindings: list[Binding]
    deletion_keys: list[str] = Field(default_factory=list)


class StateInstance(TerraformInstance):
    model_config = ConfigDict(extra="allow")


class StateResource(BaseModel):
    mode: str
    type: str
    name: str
    module: str | None = None
    instances: list[StateInstance]
    model_config = ConfigDict(extra="allow")


class StateDocument(BaseModel):
    lineage: str
    serial: int
    terraform_version: str
    resources: list[StateResource]
    outputs: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")


class ManagedKey(BaseModel):
    address: str = Field(pattern=ADDRESS_PATTERN)
    key_id: str = Field(pattern=KEY_PATTERN)


class Snapshot(BaseModel):
    state: StateDocument = Field(repr=False, exclude=True)
    managed_key: ManagedKey | None
    keys: list[IamKey]
    outputs_match: bool


class Result(BaseModel):
    account: str
    account_id: str
    iam_user: str
    status: RotationStatus
    address: str | None
    access_key_id: str | None
    expected_key_id: str | None
    retained_key_id: str | None
    terraform_version: str
    backend_bucket: str
    backend_key: str
    backend_region: str
    state_lineage: str
    state_serial: int
    cache_bucket: str | None
    cache_key: str
    bindings: list[Binding]
    terraform_outputs_match: bool
    source_secret_sync_verified: bool = False
    consumer_verification_required: bool = True

    @property
    def exit_code(self) -> int:
        return 2 if self.status in {"pending", "key_changed"} else 0


class CredentialMaterial(BaseModel):
    aws_access_key_id: SecretStr
    aws_secret_access_key: SecretStr
    aws_session_token: SecretStr | None = None
    bucket: str | None = None
    region: str | None = None
    terraform_resources_key: str | None = None

    def credentials(self, region: str) -> AWSStaticCredentials:
        values = {
            "access_key_id": self.aws_access_key_id.get_secret_value(),
            "secret_access_key": self.aws_secret_access_key.get_secret_value(),
            "region": region,
        }
        if self.aws_session_token:
            return AWSTemporaryCredentials(
                **values, session_token=self.aws_session_token.get_secret_value()
            )
        return AWSStaticCredentials(**values)


def resolve_account(
    request: Request, inventory: data.TerraformResourcesIAMKeyRotationQueryData
) -> data.AWSAccountV1:
    accounts = inventory.accounts or []
    if len(accounts) != 1 or accounts[0].name != request.account:
        raise RotationError("Expected exactly one matching AWS account")
    account = accounts[0]
    if account.disable and "terraform-resources" in (
        account.disable.integrations or []
    ):
        raise RotationError("terraform-resources is disabled for this account")
    return account


def resolve_target(
    request: Request,
    inventory: data.TerraformResourcesIAMKeyRotationQueryData,
    material: CredentialMaterial | None = None,
) -> tuple[Target, data.AWSAccountV1]:
    account = resolve_account(request, inventory)
    backends = [
        b
        for b in (
            account.terraform_state.integrations if account.terraform_state else []
        )
        if b.integration.replace("-", "_") == "terraform_resources"
    ]
    if len(backends) > 1:
        raise RotationError(
            "Multiple terraform-resources state backends are configured"
        )
    # Match TerrascriptClient.state_bucket_for_account: explicit per-integration
    # settings override the backend metadata stored with automation credentials.
    if backends and account.terraform_state:
        bucket, key, region = (
            account.terraform_state.bucket,
            backends[0].key,
            account.terraform_state.region,
        )
    elif (
        material
        and material.bucket
        and material.terraform_resources_key
        and material.region
    ):
        bucket, key, region = (
            material.bucket,
            material.terraform_resources_key,
            material.region,
        )
    else:
        raise RotationError(
            "No complete terraform-resources backend in account settings or automation credential metadata"
        )
    bindings = []
    for namespace in inventory.namespaces or []:
        if namespace.delete or not namespace.managed_external_resources:
            continue
        if namespace.cluster.disable and "terraform-resources" in (
            namespace.cluster.disable.integrations or []
        ):
            continue
        for spec in namespace.external_resources or []:
            if (
                not isinstance(spec, data.NamespaceTerraformProviderResourceAWSV1)
                or spec.provider != "aws"
                or spec.provisioner.name != request.account
            ):
                continue
            for resource in spec.resources:
                if (
                    not isinstance(resource, RESOURCE_TYPES)
                    or resource.identifier != request.iam_user
                ):
                    continue
                if (
                    isinstance(resource, data.NamespaceTerraformResourceCloudWatchV1)
                    and resource.managed_by_erv2
                ):
                    raise RotationError(
                        "This IAM user has an ERv2 declaration; use the ERv2 command"
                    )
                prefix = f"{resource.identifier}-{resource.provider.replace('_', '-')}"
                bindings.append(
                    Binding(
                        cluster=namespace.cluster.name,
                        namespace=namespace.name,
                        provider=resource.provider,
                        secret_name=resource.output_resource_name or prefix,
                        output_key=prefix + "__aws_access_key_id",
                    )
                )
    if not bindings:
        raise RotationError(
            "No enabled legacy IAM-key resource declaration matches this user"
        )
    return Target(
        account=account.name,
        account_id=account.uid,
        iam_user=request.iam_user,
        bucket=bucket,
        key=key,
        region=region,
        bindings=bindings,
        deletion_keys=account.delete_keys or [],
    ), account


def select_key(
    state: StateDocument, user: str, expected_address: str | None
) -> ManagedKey | None:
    matches = []
    for resource in state.resources:
        if resource.mode != "managed" or resource.type != "aws_iam_access_key":
            continue
        address = f"{resource.type}.{resource.name}"
        for instance in resource.instances:
            if instance.attributes.get("user") != user:
                if address == expected_address:
                    raise RotationError("Expected address belongs to another IAM user")
                continue
            attributes = IamStateAttributes.model_validate(instance.attributes)
            if (
                resource.module
                or instance.index_key is not None
                or instance.deposed
                or instance.status == "tainted"
            ):
                raise RotationError(
                    "Only an untainted, unindexed root IAM access-key binding is supported"
                )
            if expected_address is not None and address != expected_address:
                raise RotationError(
                    "IAM user's state address changed; inspect before continuing"
                )
            matches.append(ManagedKey(address=address, key_id=attributes.id))
    if len(matches) > 1:
        raise RotationError("Multiple Terraform IAM key bindings match this user")
    return matches[0] if matches else None


class RotationRuntime(Protocol):
    target: Target
    cache_bucket: str | None

    def snapshot(self, expected_address: str | None) -> Snapshot: ...
    def remove(self, before: Snapshot, address: str) -> None: ...
    def invalidate(self, key: CacheKeyWithDigest) -> None: ...


def validate_request(request: Request) -> None:
    if request.verify and not request.dry_run:
        raise RotationError("--verify is read-only")
    if (request.verify or not request.dry_run) and (
        not request.expected_key_id or not request.expected_address
    ):
        raise RotationError(
            "Execution and verification require --expected-key-id and --expected-address from inspection"
        )
    if not request.dry_run and not request.expected_cache_bucket:
        raise RotationError(
            "Execution requires the matching --expected-cache-bucket from inspection"
        )
    if not request.dry_run and not request.account_quiesced:
        raise RotationError(
            "Pause account-wide Terraform applies, then supply --account-quiesced; the legacy backend has no configured state lock"
        )


def rotate(request: Request, runtime: RotationRuntime) -> Result:
    validate_request(request)
    if not request.dry_run and request.expected_cache_bucket != runtime.cache_bucket:
        raise RotationError(
            "Cache bucket changed since inspection; no mutation attempted"
        )
    target = runtime.target
    if (request.account, request.iam_user) != (target.account, target.iam_user):
        raise RotationError("Resolved target differs from the request")
    cache_key = CacheKeyWithDigest(
        integration="terraform-resources",
        integration_version=request.integration_version,
        dry_run=False,
        cache_source_digest="",
        shard=target.account,
    )
    snapshot = runtime.snapshot(request.expected_address)
    managed = snapshot.managed_key
    old = request.expected_key_id or (managed.key_id if managed else None)
    keys = {k.access_key_id: k.status for k in snapshot.keys}

    def result(status: RotationStatus) -> Result:
        return Result(
            account=target.account,
            account_id=target.account_id,
            iam_user=target.iam_user,
            status=status,
            address=managed.address if managed else request.expected_address,
            access_key_id=managed.key_id if managed else None,
            expected_key_id=request.expected_key_id,
            retained_key_id=old
            if old
            and keys.get(old) == "Active"
            and (managed is None or managed.key_id != old)
            else None,
            terraform_version=snapshot.state.terraform_version,
            backend_bucket=target.bucket,
            backend_key=target.key,
            backend_region=target.region,
            state_lineage=snapshot.state.lineage,
            state_serial=snapshot.state.serial,
            cache_bucket=runtime.cache_bucket,
            cache_key=str(cache_key),
            bindings=target.bindings,
            terraform_outputs_match=snapshot.outputs_match,
        )

    if request.verify:
        if (
            managed
            and managed.key_id != old
            and keys.get(managed.key_id) == "Active"
            and snapshot.outputs_match
        ):
            if old not in keys:
                return result("old_key_retired")
            if keys.get(old) == "Active":
                return result("key_created")
        return result("pending")
    if managed and old != managed.key_id:
        return result("key_changed")
    if old in target.deletion_keys:
        raise RotationError(
            "Old key is listed in deleteKeys; remove its scheduled retirement before no-downtime preparation"
        )
    if not old or keys != {old: "Active"}:
        raise RotationError(
            "Preparation requires exactly one IAM key: the expected Active old key"
        )
    if request.dry_run:
        if managed is None:
            raise RotationError(
                "Key state is absent; use the original expected key ID and address to resume"
            )
        return result("would_prepare")
    if managed:
        runtime.remove(snapshot, managed.address)
    after = runtime.snapshot(request.expected_address)
    if after.keys != snapshot.keys:
        raise RotationError(
            "IAM keys changed during preparation; inspect before resuming"
        )
    if after.managed_key is not None:
        raise RotationError(
            "A managed key appeared; inspect before invalidating the cache"
        )
    runtime.invalidate(cache_key)
    snapshot, managed = after, after.managed_key
    return result("requested")


class Runtime:
    def __init__(
        self,
        target: Target,
        credentials: AWSStaticCredentials,
        reader: SecretReaderBase,
        terraform_binary: str,
        verify: bool,
    ) -> None:
        self.target = target
        self.credentials = credentials
        self.api = AWSApi(credentials)
        self.cache: EarlyExitCache | None = None
        self.cache_bucket: str | None = None
        self.temporary = tempfile.TemporaryDirectory(prefix="iam-key-rotation.")
        self.directory = Path(self.temporary.name)
        self.terraform_binary = terraform_binary
        try:
            identity = self.api.sts.client.get_caller_identity()
            if (
                identity["Account"] != target.account_id
                or identity["Arn"].split("/")[-1] == target.iam_user
            ):
                raise RotationError(
                    "Wrong AWS identity, or refusing to rotate the executing identity's key"
                )
            if not verify:
                self.cache = EarlyExitCache.build(reader)
                self.cache_bucket = self.cache.state.bucket
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.cache:
            self.cache.cleanup()
        self.api.close()
        self.temporary.cleanup()

    def snapshot(self, expected_address: str | None) -> Snapshot:
        response = self.api.s3.client.get_object(
            Bucket=self.target.bucket, Key=self.target.key
        )
        try:
            state = StateDocument.model_validate_json(response["Body"].read())
        finally:
            response["Body"].close()
        managed = select_key(state, self.target.iam_user, expected_address)
        response_keys = self.api.iam.client.list_access_keys(
            UserName=self.target.iam_user
        )
        if response_keys.get("IsTruncated"):
            raise RotationError("Unexpected IAM access-key pagination")
        keys = [IamKey.model_validate(k) for k in response_keys["AccessKeyMetadata"]]
        outputs_match = managed is not None and all(
            state.outputs.get(binding.output_key, {}).get("value") == managed.key_id
            for binding in self.target.bindings
        )
        return Snapshot(
            state=state, managed_key=managed, keys=keys, outputs_match=outputs_match
        )

    def remove(self, before: Snapshot, address: str) -> None:
        binary = shutil.which(self.terraform_binary)
        if not binary:
            raise RotationError("Terraform executable not found")
        environment = {
            k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "TF_"))
        }
        cli_config = self.directory / "terraformrc"
        cli_config.touch(mode=0o600)
        environment.update(
            self.credentials.as_env_vars(),
            TF_IN_AUTOMATION="true",
            TF_INPUT="0",
            TF_DATA_DIR=str(self.directory / ".terraform"),
            TF_CLI_CONFIG_FILE=str(cli_config),
            AWS_CONFIG_FILE=str(cli_config),
            AWS_SHARED_CREDENTIALS_FILE=os.devnull,
            AWS_EC2_METADATA_DISABLED="true",
            CHECKPOINT_DISABLE="1",
        )

        def terraform(*args: str) -> str:
            return checked(
                [binary, f"-chdir={self.directory}", *args],
                phase="Terraform " + args[0],
                env=environment,
            )

        version = TerraformVersion.model_validate_json(
            terraform("version", "-json")
        ).terraform_version
        if version != before.state.terraform_version:
            raise RotationError(
                "Terraform executable version must exactly match the remote state's terraform_version"
            )
        configuration = TerraformConfiguration(
            terraform=TerraformSettings(
                backend=BackendConfiguration(
                    s3=BackendS3(
                        bucket=self.target.bucket,
                        key=self.target.key,
                        region=self.target.region,
                    )
                )
            )
        )
        path = self.directory / "backend.tf.json"
        path.write_text(configuration.model_dump_json())
        path.chmod(0o600)
        terraform("init", "-backend-only", "-get=false", "-input=false", "-no-color")
        preview = terraform("state", "rm", "-dry-run", "-lock-timeout=180s", address)
        if re.findall(r"^Would remove (\S+)", preview, re.MULTILINE) != [address]:
            raise RotationError(
                "Terraform state-removal preview differs from the expected address"
            )
        fresh = self.snapshot(address)
        if fresh != before:
            raise RotationError(
                "Remote state or IAM keys changed during preflight; inspect and retry"
            )
        terraform("state", "rm", "-lock-timeout=180s", address)
        after = self.snapshot(address)
        expected = before.state.model_copy(deep=True)
        expected.resources = [
            r
            for r in expected.resources
            if f"{r.type}.{r.name}" != address or r.mode != "managed" or r.module
        ]
        expected.serial += 1
        if (
            after.state != expected
            or after.managed_key is not None
            or after.keys != before.keys
        ):
            raise RotationError(
                "Post-removal state or IAM keys differ from the exact expected change; inspect before resuming"
            )

    def invalidate(self, key: CacheKeyWithDigest) -> None:
        if self.cache is None:
            raise RotationError("Reconciliation cache is not configured")
        exists, _ = self.cache.state.head(str(key))
        if exists:
            self.cache.delete(key)


class TerraformVersion(BaseModel):
    terraform_version: str


class BackendS3(BaseModel):
    bucket: str
    key: str
    region: str


class BackendConfiguration(BaseModel):
    s3: BackendS3


class TerraformSettings(BaseModel):
    backend: BackendConfiguration


class TerraformConfiguration(BaseModel):
    terraform: TerraformSettings


def run_single(
    request: Request, reader: SecretReaderBase, terraform_binary: str = "terraform"
) -> Result:
    validate_request(request)
    # Suppress third-party logs that may contain Terraform state or Vault input.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        inventory = data.query(
            gql.get_api().query, variables={"filter": {"name": request.account}}
        )
        account = resolve_account(request, inventory)
        material = CredentialMaterial.model_validate(
            reader.read_all_secret(account.automation_token)
        )
        target, _ = resolve_target(request, inventory, material)
        runtime = Runtime(
            target,
            material.credentials(target.region),
            reader,
            terraform_binary,
            request.verify,
        )
        try:
            return rotate(request, runtime)
        finally:
            runtime.close()
    finally:
        logging.disable(previous)
