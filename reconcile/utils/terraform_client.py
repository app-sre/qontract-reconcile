import json
import logging
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import (
    Generator,
    Iterable,
    Mapping,
)
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from subprocess import CalledProcessError
from threading import Lock
from typing import (
    IO,
    Any,
    cast,
)

from botocore.errorfactory import ClientError
from sretoolbox.utils import (
    retry,
    threaded,
)

import reconcile.utils.lean_terraform_client as lean_tf
from reconcile.typed_queries.app_interface_custom_messages import (
    get_app_interface_custom_message,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.aws_helper import get_region_from_availability_zone
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)

ALLOWED_TF_SHOW_FORMAT_VERSION = "1.2"
DATE_FORMAT = "%Y-%m-%d"
PROVIDER_LOG_REGEX = (
    r""".*\s(?:\[INFO]|\[WARN]|\[ERROR])\s.+\s(?:\[WARN]|\[ERROR])\s.*"""
)
PROVIDER_LOG_IGNORE_REGEX = (
    r""".*(?:ObjectLockConfigurationNotFoundError|WaitForState).*"""
)
TERRAFORM_LOG_LEVEL = "TRACE"  # can change to INFO after tf 0.15


@dataclass
class AccountUser:
    account: str
    user: str


@dataclass(frozen=True, eq=True)
class TerraformSpec:
    name: str
    working_dir: str


class TerraformCommandError(CalledProcessError):
    pass


class DeletionApprovalExpirationValueError(Exception):
    pass


class TerraformClient:  # pylint: disable=too-many-public-methods
    def __init__(
        self,
        integration: str,
        integration_version: str,
        integration_prefix: str,
        accounts: Iterable[Mapping[str, Any]],
        working_dirs: Mapping[str, str],
        thread_pool_size: int,
        aws_api: AWSApi | None = None,
        init_users=False,
    ):
        self.integration = integration
        self.integration_version = integration_version
        self.integration_prefix = integration_prefix
        self.working_dirs = working_dirs
        self.accounts = {a["name"]: a for a in accounts}
        self.parallelism = thread_pool_size
        self.thread_pool_size = thread_pool_size
        self._aws_api = aws_api
        self._log_lock = Lock()
        self.apply_count = 0

        self.specs: list[TerraformSpec] = []
        self.init_specs()
        self.outputs: dict = {}
        self.init_outputs()

        self.OUTPUT_TYPE_SECRETS = "Secrets"
        self.OUTPUT_TYPE_PASSWORDS = "enc-passwords"
        self.OUTPUT_TYPE_CONSOLEURLS = "console-urls"

        self.users: dict = {}
        if init_users:
            self.init_existing_users()

    def init_existing_users(self):
        self.users = {
            account: list(self.format_output(output, self.OUTPUT_TYPE_PASSWORDS).keys())
            for account, output in self.outputs.items()
        }

    def increment_apply_count(self):
        self.apply_count += 1

    def should_apply(self) -> bool:
        return self.apply_count > 0

    def get_new_users(self):
        new_users = []
        self.init_outputs()  # get updated output
        for account, output in self.outputs.items():
            user_passwords = self.format_output(output, self.OUTPUT_TYPE_PASSWORDS)
            console_urls = self.format_output(output, self.OUTPUT_TYPE_CONSOLEURLS)
            for user_name, enc_password in user_passwords.items():
                if AccountUser(account, user_name) not in self.created_users:
                    continue
                new_users.append((
                    account,
                    console_urls[account],
                    user_name,
                    enc_password,
                ))
        return new_users

    def init_specs(self):
        self.specs = [
            TerraformSpec(name=name, working_dir=wd)
            for name, wd in self.working_dirs.items()
        ]
        for spec in self.specs:
            self.terraform_init(spec)

    @contextmanager
    def _terraform_log_file(
        self, working_dir: str
    ) -> Generator[tuple[IO, dict[str, str]], None, None]:
        with tempfile.NamedTemporaryFile(dir=working_dir) as f:
            env = {
                "TF_LOG": TERRAFORM_LOG_LEVEL,
                "TF_LOG_PATH": f.name,
            }
            yield f, env

    @retry(exceptions=TerraformCommandError)
    def terraform_init(self, spec: TerraformSpec):
        with self._terraform_log_file(spec.working_dir) as (f, env):
            return_code, stdout, stderr = lean_tf.init(spec.working_dir, env=env)
            log = f.read().decode("utf-8")
        error = self.check_output(spec.name, "init", return_code, stdout, stderr, log)
        if error:
            raise TerraformCommandError(
                return_code, "init", output=stdout, stderr=stderr
            )

    def init_outputs(self):
        results = threaded.run(self.terraform_output, self.specs, self.thread_pool_size)
        self.outputs = dict(results)

    @retry(exceptions=TerraformCommandError)
    def terraform_output(self, spec: TerraformSpec):
        with self._terraform_log_file(spec.working_dir) as (f, env):
            return_code, stdout, stderr = lean_tf.output(spec.working_dir, env=env)
            log = f.read().decode("utf-8")
        error = self.check_output(spec.name, "output", return_code, stdout, stderr, log)
        no_output_error = (
            "The module root could not be found. There is nothing to output."
        )
        if error:
            if no_output_error in stderr:
                stdout = "{}"
            else:
                raise TerraformCommandError(
                    return_code, "output", output=stdout, stderr=stderr
                )
        return spec.name, json.loads(stdout)

    # terraform plan
    def plan(self, enable_deletion):
        errors = False
        disabled_deletions_detected = False
        results = threaded.run(
            self.terraform_plan,
            self.specs,
            self.thread_pool_size,
            enable_deletion=enable_deletion,
        )

        self.created_users = []
        for disabled_deletion_detected, created_users, error in results:
            if error:
                errors = True
            if disabled_deletion_detected:
                disabled_deletions_detected = True
            self.created_users.extend(created_users)
        return disabled_deletions_detected, errors

    def safe_plan(self, enable_deletion: bool) -> None:
        """Raises exception if errors are detected at plan step"""
        disable_deletions_detected, errors = self.plan(enable_deletion)

        if errors:
            raise RuntimeError("Terraform plan has errors")
        if disable_deletions_detected:
            raise RuntimeError("Terraform plan has disabled deletions detected")

    @retry()
    def terraform_plan(
        self, spec: TerraformSpec, enable_deletion: bool
    ) -> tuple[bool, list[AccountUser], bool]:
        with self._terraform_log_file(spec.working_dir) as (f, env):
            return_code, stdout, stderr = lean_tf.plan(
                spec.working_dir,
                spec.name,
                env=env,
            )
            log = f.read().decode("utf-8")
        error = self.check_output(spec.name, "plan", return_code, stdout, stderr, log)
        if error:
            return False, [], error
        disabled_deletion_detected, created_users = self.log_plan_diff(
            spec, enable_deletion
        )
        return disabled_deletion_detected, created_users, error

    @staticmethod
    def _resource_diff_changed_fields(
        action: str, change: Mapping[str, Any]
    ) -> set[str]:
        if action != "update":
            return set()

        before = change.get("before", {})
        if not before:
            before = {}
        after = change.get("after", {})
        if not after:
            after = {}

        keys = set(before)
        keys.update(set(after))

        changed_fields = set()

        for k in keys:
            # JSON format is subject of change, adding try catch to make sure
            # key errors do not crash integration
            try:
                if k in before and k not in after:
                    # computed value
                    changed_fields.add(k)
                elif before.get(k, "") != after.get(k, ""):
                    # changed value
                    changed_fields.add(k)
            except KeyError:
                logging.error("Key error in _resource_diff_changed_fields, key: %s", k)
        return changed_fields

    def log_plan_diff(
        self,
        spec: TerraformSpec,
        enable_deletion: bool,
    ) -> tuple[bool, list]:
        disabled_deletion_detected = False
        name = spec.name
        account_enable_deletion = self.accounts[name].get("enableDeletion") or False
        # deletions are allowed
        # if enableDeletion is true for an account
        # or if the integration's enable_deletion is true
        deletions_allowed = enable_deletion or account_enable_deletion
        created_users: list[AccountUser] = []

        output = lean_tf.show_json(spec.working_dir, name)
        format_version = output.get("format_version")
        if format_version != ALLOWED_TF_SHOW_FORMAT_VERSION:
            raise NotImplementedError("terraform show untested format version")

        # https://www.terraform.io/docs/internals/json-format.html
        # Terraform is not yet fully able to
        # track changes to output values, so the actions indicated may not be
        # fully accurate, but the "after" value will always be correct.
        # to overcome the "before" value not being accurate,
        # we find it in the previously initiated outputs.
        output_changes = output.get("output_changes", {})
        for output_name, output_change in output_changes.items():
            before = self.outputs[name].get(output_name, {}).get("value")
            after = output_change.get("after")
            if before != after:
                logging.info(["update", name, "output", output_name])
                self.increment_apply_count()

        # A way to detect deleted outputs is by comparing
        # the prior state with the output changes.
        # the output changes do not contain deleted outputs
        # while the prior state does. for the outputs to
        # actually be deleted, we should apply.
        prior_outputs = (
            output.get("prior_state", {}).get("values", {}).get("outputs", {})
        )
        deleted_outputs = [po for po in prior_outputs if po not in output_changes]
        for output_name in deleted_outputs:
            logging.info(["delete", name, "output", output_name])
            self.increment_apply_count()

        resource_changes = output.get("resource_changes")
        if resource_changes is None:
            return disabled_deletion_detected, created_users

        always_enabled_deletions = {
            "random_id",
            "aws_lb_target_group_attachment",
            "aws_iam_user_policy",
            "cloudflare_record",  # This is because a zone can contain up to one thousand records and it's not practical to require adding each record to deletionApprovals
        }

        # https://www.terraform.io/docs/internals/json-format.html
        for resource_change in resource_changes:
            resource_type = resource_change["type"]
            resource_name = resource_change["name"]
            resource_change = resource_change["change"]
            actions = resource_change["actions"]
            for action in actions:
                if action == "no-op":
                    logging.debug([action, name, resource_type, resource_name])
                    continue
                if action == "update" and resource_type == "aws_db_instance":
                    self.validate_db_upgrade(name, resource_name, resource_change)
                    # Ignore RDS modifications that are going to occur during the next
                    # maintenance window. This can be up to 7 days away and will cause
                    # unnecessary Terraform state updates until they complete.
                    if self._can_skip_rds_modifications(
                        name, resource_name, resource_change
                    ):
                        logging.debug(
                            f"Resource {resource_name} contains pending changes that "
                            f"can be skipped, should_apply will not be set."
                        )
                        continue
                with self._log_lock:
                    logging.info([
                        action,
                        name,
                        resource_type,
                        resource_name,
                        self._resource_diff_changed_fields(action, resource_change),
                    ])
                    self.increment_apply_count()
                if action == "create":
                    if resource_type == "aws_iam_user_login_profile":
                        created_users.append(AccountUser(name, resource_name))
                if action == "delete":
                    if resource_type in always_enabled_deletions:
                        continue

                    if not deletions_allowed and not self.deletion_approved(
                        name, resource_type, resource_name
                    ):
                        disabled_deletion_detected = True
                        instructions = (
                            get_app_interface_custom_message(
                                "disabled-deletion-instructions"
                            )
                            or ""
                        )
                        logging.error(f"'delete' action is not enabled. {instructions}")
                    if resource_type == "aws_db_instance":
                        deletion_protected = resource_change["before"].get(
                            "deletion_protection"
                        )
                        if deletion_protected:
                            disabled_deletion_detected = True
                            logging.error(
                                "'delete' action is not enabled for "
                                "deletion protected RDS instance: "
                                f"{resource_name}. Please set "
                                "deletion_protection to false in a new MR. "
                                "The new MR must be merged first."
                            )
        return disabled_deletion_detected, created_users

    def deletion_approved(self, account_name, resource_type, resource_name):
        account = self.accounts[account_name]
        deletion_approvals = account.get("deletionApprovals")
        if not deletion_approvals:
            return False
        now = datetime.utcnow()
        for da in deletion_approvals:
            try:
                expiration = datetime.strptime(
                    da["expiration"], DATE_FORMAT
                ) + timedelta(days=1)
            except ValueError:
                raise DeletionApprovalExpirationValueError(
                    f"[{account_name}] expiration not does not match "
                    f"date format {DATE_FORMAT}. details: "
                    f"type: {da['type']}, name: {da['name']}"
                )
            if (
                resource_type == da["type"]
                and resource_name == da["name"]
                and now <= expiration
            ):
                return True

        return False

    # terraform apply
    def apply(self):
        errors = threaded.run(self.terraform_apply, self.specs, self.thread_pool_size)
        return any(errors)

    def terraform_apply(self, spec: TerraformSpec):
        with self._terraform_log_file(spec.working_dir) as (f, env):
            return_code, stdout, stderr = lean_tf.apply(
                spec.working_dir,
                spec.name,
                env=env,
            )
            log = f.read().decode("utf-8")
        error = self.check_output(spec.name, "apply", return_code, stdout, stderr, log)
        return error

    def get_terraform_output_secrets(self) -> dict[str, dict[str, dict[str, str]]]:
        data = {}
        for account, output in self.outputs.items():
            data[account] = self.format_output(output, self.OUTPUT_TYPE_SECRETS)

        return data

    @staticmethod
    def get_replicas_info(
        resource_specs: Iterable[ExternalResourceSpec],
    ) -> dict[str, dict[str, str]]:
        """
        finds the source resources of RDS replicas

        the key of the returned dict is the identifier of the replica
        and the value is the resource of the replicas master db
        """
        replicas_info: dict[str, dict[str, str]] = defaultdict(dict)

        for spec in resource_specs:
            tf_resource = spec.resource
            replica_src = tf_resource.get("replica_source")
            if replica_src:
                replica_source_name = f'{replica_src}-{tf_resource.get("provider")}'
                # Creating a dict that is convenient to use inside the
                # loop processing the formatted_output
                replicas_info[spec.provisioner_name][spec.output_prefix] = (
                    replica_source_name
                )

        return replicas_info

    def format_output(self, output, type):
        # data is a dictionary of dictionaries
        data = {}
        if output is None:
            return data

        enc_pass_pfx = f"{self.integration_prefix}_{self.OUTPUT_TYPE_PASSWORDS}"
        console_urls_pfx = f"{self.integration_prefix}_{self.OUTPUT_TYPE_CONSOLEURLS}"
        for k, v in output.items():
            # the integration creates outputs of the form
            # 0.11: output_secret_name[secret_key] = secret_value
            # 0.13: output_secret_name__secret_key = secret_value
            # in case of manual debugging, additional outputs
            # may be added, and may (should) not conform to this
            # naming convention. as outputs are persisted to remote
            # state, we would not want them to affect any runs
            # of the integration.
            if "__" not in k:
                continue

            # if the output is of the form 'qrtf.enc-passwords[user_name]'
            # this is a user output and should not be formed to a Secret
            # but rather to an invitaion e-mail.
            # this is determined by the 'type' argument
            if type == self.OUTPUT_TYPE_PASSWORDS and not k.startswith(enc_pass_pfx):
                continue

            if type == self.OUTPUT_TYPE_CONSOLEURLS and not k.startswith(
                console_urls_pfx
            ):
                continue

            # Secrets is in essence the default value
            # because we don't (currently) have a way
            # to clasify it (secret names are free text)
            if type == self.OUTPUT_TYPE_SECRETS and (
                k.startswith(enc_pass_pfx) or k.startswith(console_urls_pfx)
            ):
                continue

            k_split = k.split("__")
            resource_name = k_split[0]
            field_key = k_split[1]
            if field_key.startswith("db"):
                # since we can't use '.' in output keys
                # and we want to maintain compatability
                # replace '_' with '.' when this is a db secret
                field_key = field_key.replace("db_", "db.")
            field_value = v["value"]
            if resource_name not in data:
                data[resource_name] = {}
            data[resource_name][field_key] = field_value

        if len(data) == 1 and type in {
            self.OUTPUT_TYPE_PASSWORDS,
            self.OUTPUT_TYPE_CONSOLEURLS,
        }:
            return data[list(data.keys())[0]]
        return data

    def populate_terraform_output_secrets(
        self,
        resource_specs: ExternalResourceSpecInventory,
        init_rds_replica_source: bool = False,
    ) -> None:
        """
        find the terraform output data for each resource spec and populate its `secret` field.
        if the `init_rds_replica_source` a replica RDS gets its DB user and password fields
        populated by looking at the replica source DB.
        """
        self.init_outputs()  # get updated output
        terraform_output_secrets = self.get_terraform_output_secrets()
        if init_rds_replica_source:
            replicas_info = self.get_replicas_info(resource_specs.values())
        else:
            replicas_info = {}

        self._populate_terraform_output_secrets(
            resource_specs,
            terraform_output_secrets,
            self.integration_prefix,
            replicas_info,
        )

    @staticmethod
    def _populate_terraform_output_secrets(
        resource_specs: ExternalResourceSpecInventory,
        terraform_output_secrets: Mapping[str, Mapping[str, Mapping[str, str]]],
        integration_prefix: str,
        replica_sources: Mapping[str, Mapping[str, str]],
    ) -> None:
        for spec in resource_specs.values():
            secret = terraform_output_secrets.get(spec.provisioner_name, {}).get(
                spec.output_prefix, None
            )
            if not secret:
                continue
            secret_copy = dict(secret)

            # find out about replica source
            replica_source = replica_sources.get(spec.provisioner_name, {}).get(
                spec.output_prefix
            )
            if replica_source:
                # Grabbing the username/password from the
                # replica_source and using them in the
                # replica. This is needed because we can't
                # set username/password for a replica in
                # terraform.
                replica_source_secret = terraform_output_secrets.get(
                    spec.provisioner_name, {}
                ).get(replica_source)
                if replica_source_secret:
                    replica_src_user = replica_source_secret.get("db.user")
                    replica_src_password = replica_source_secret.get("db.password")
                    if replica_src_user and replica_src_password:
                        secret_copy["db.user"] = replica_src_user
                        secret_copy["db.password"] = replica_src_password

            # clean metadata
            for key in secret.keys():
                if integration_prefix in key:
                    secret_copy.pop(key)

            spec.secret = secret_copy

    def check_output(
        self,
        name: str,
        cmd: str,
        return_code: int,
        stdout: str,
        stderr: str,
        log: str,
    ) -> bool:
        error_occured = return_code != 0
        line_format = "[{} - {}] {}"
        stdout, stderr, log = self.split_to_lines(stdout, stderr, log)
        provider_log_re = re.compile(PROVIDER_LOG_REGEX)
        provider_log_ignore_re = re.compile(PROVIDER_LOG_IGNORE_REGEX)
        with self._log_lock:
            for line in stdout:
                logging.debug(line_format.format(name, cmd, line))
            if error_occured:
                for line in stderr:
                    logging.error(line_format.format(name, cmd, line))
            else:
                for line in stderr:
                    logging.warning(line_format.format(name, cmd, line))
            for line in log:
                if provider_log_re.match(line) and not provider_log_ignore_re.match(
                    line
                ):
                    logging.warning(line_format.format(name, cmd, line))
        return error_occured

    @staticmethod
    def split_to_lines(*outputs):
        split_outputs = []
        try:
            for output in outputs:
                output_lines = [ln for ln in output.split("\n") if ln]
                split_outputs.append(output_lines)
        except Exception:
            logging.warning("failed to split outputs to lines.")
            return outputs
        if len(split_outputs) == 1:
            return split_outputs[0]
        return split_outputs

    def cleanup(self):
        if self._aws_api is not None:
            self._aws_api.cleanup()
        for _, wd in self.working_dirs.items():
            shutil.rmtree(wd)

    def _can_skip_rds_modifications(
        self, account_name: str, resource_name: str, resource_change: Mapping[str, Any]
    ) -> bool:
        """Skip pending RDS modifications.

        Determine whether the RDS resource has pending modifications to the
        underlying database instance that can be skipped at this time.  If the
        apply_immediately property of the resource has not been set, then any
        pending changes will be automatically applied during next scheduled
        maintenance window.

        :param str account_name: Name of the AWS account.
        :param str resource_name: Name of the RDS database instance.  This is the
            unique database instance identifier.
        :param resource_change: A dict that describes changes pending, before
            and after, for the underlying resource.  Format of the data follows
            Terraform's JSON-formatted output specification, see:
              https://developer.hashicorp.com/terraform/internals/json-format
        :type resource_changes: typing.Mapping[str, Any]
        :returns: A bool to indicate that any pending modifications to an RDS
            database instance are safe to ignore and a Terraform apply should be
            skipped for the underlying resource.
        :rtype: bool
        """
        # A commonly changed RDS database settings that can be applied either
        # immediately or during the next scheduled maintenance window, see:
        #  https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.DBInstance.Modifying.html#USER_ModifyInstance.Settings
        #
        # Note that changing the RDS database identifier (the database name) is
        # a complex operation that also involves Terraform performing a resource
        # replacement and thus it's not included here, see:
        #   https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_RenameInstance.html
        allowed_modifications: dict[str, str] = {
            "engine_version": "EngineVersion",
            "storage_type": "StorageType",
            "allocated_storage": "AllocatedStorage",
            "instance_class": "DBInstanceClass",
            "multi_az": "MultiAZ",
            "iops": "Iops",
        }
        before = resource_change["before"]
        after = resource_change["after"]
        changed_resource_arguments = [
            key for key, value in before.items() if value != after.get(key)
        ]
        logging.debug(
            f"Resource {resource_name} changes in Terraform: {changed_resource_arguments}"
        )
        if changed_resource_arguments and self._aws_api is not None:
            region_name = get_region_from_availability_zone(before["availability_zone"])
            try:
                response = self._aws_api.describe_rds_db_instance(
                    account_name, resource_name, region_name=region_name
                )
            except ClientError as e:
                # The RDS database might have been already removed, or there was
                # a resource name change, and we no longer use valid references.
                # There is no need to delay apply.
                if e.response.get("Error", {}).get("Code") == "DBInstanceNotFound":
                    logging.debug(f"Resource does not exist: {resource_name}")
                    return False
                raise
            pending_modified_values = response["DBInstances"][0].get(
                "PendingModifiedValues"
            )
            logging.debug(
                f"Resource {resource_name} changes in AWS: {pending_modified_values}"
            )
            # The PendingModifiedValues attribute might not be included as part
            # of the RDS database instance object. However, we expect it to be
            # included here, especially since, at this point, Terraform also
            # claims a pending change for the underlying resource. Thus if we
            # can't agree on AWS API vs Terraform state, then perhaps changes
            # have already been applied.
            if not pending_modified_values:
                return False
            changed_values: list[str] = []
            for argument in changed_resource_arguments:
                # We skip anything that is not safe to leave as pending.
                value = allowed_modifications.get(argument)
                if (
                    value in pending_modified_values
                    and cast(dict[str, str], pending_modified_values)[value]
                    == after[argument]
                ):
                    changed_values.append(argument)
            # A change to the resource on Terraform's side without being reflected
            # on the AWS' side should not delay the apply, so that a new change to
            # the underlying resource can be scheduled and added to the set of
            # pending changes.
            return not set(changed_resource_arguments) - set(changed_values)
        return False

    def validate_db_upgrade(
        self, account_name: str, resource_name: str, resource_change: Mapping[str, Any]
    ):
        """
        Determine whether the RDS engine version upgrade is valid.

        :param str account_name: Name of the AWS account.
        :param str resource_name: Name of the RDS database instance.  This is the
            unique database instance identifier.
        :param resource_change: A dict that describes changes pending, before
            and after, for the underlying resource.  Format of the data follows
            Terraform's JSON-formatted output specification, see:
              https://developer.hashicorp.com/terraform/internals/json-format
        """

        before = resource_change["before"]
        engine = before["engine"]
        before_version = before["engine_version"]
        after = resource_change["after"]
        after_version = after["engine_version"]
        if after_version == before_version:
            return

        region_name = get_region_from_availability_zone(before["availability_zone"])
        if self._aws_api is not None:
            valid_upgrade_target = self._aws_api.get_db_valid_upgrade_target(
                account_name, engine, before_version, region_name=region_name
            )
            if not valid_upgrade_target:
                # valid_upgrade_target can be empty when current version is no longer supported by AWS.
                # In this case, we can't validate it, so skip.
                logging.warning(
                    f"No valid upgrade target available, skip validation for {resource_name}."
                )
                return
            target = next(
                (
                    t
                    for t in valid_upgrade_target
                    if t["EngineVersion"] == after_version
                ),
                None,
            )
            if target is None:
                raise ValueError(
                    f"Cannot upgrade RDS instance: {resource_name} "
                    f"from {before_version} to {after_version}"
                )
            allow_major_version_upgrade = after.get(
                "allow_major_version_upgrade",
                False,
            )
            if target["IsMajorVersionUpgrade"] and not allow_major_version_upgrade:
                raise ValueError(
                    "allow_major_version_upgrade is not enabled for upgrading RDS instance: "
                    f"{resource_name} to a new major version."
                )


class TerraformPlanFailed(Exception):
    pass


class TerraformApplyFailed(Exception):
    pass


class TerraformDeletionDetected(Exception):
    pass
