import logging
from collections.abc import Callable
from typing import Any

import jinja2

from reconcile.gql_definitions.terraform_init.aws_accounts import AWSAccountV1
from reconcile.gql_definitions.terraform_init.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.terraform_init.merge_request import Renderer, create_parser
from reconcile.terraform_init.merge_request_manager import MergeRequestManager, MrData
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.aws_account_tags import get_aws_account_tags
from reconcile.typed_queries.external_resources import get_settings
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from reconcile.utils.datetime_util import utc_now
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.gql import GqlApi
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "terraform-init"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class TerraformInitIntegrationParams(PydanticRunParams):
    account_name: str | None
    # To avoid the accidental deletion of the resource file, explicitly set the
    # qontract.cli option in the integration extraArgs!
    state_tmpl_resource: str = "/terraform-init/terraform-state.yml"
    cloudformation_template_resource: str = (
        "/terraform-init/terraform-state-s3-bucket.yaml"
    )
    cloudformation_import_template_resource: str = (
        "/terraform-init/terraform-state-s3-bucket-import.yaml"
    )
    template_collection_root_path: str = "data/templating/collections/terraform-init"


class TerraformInitIntegration(
    QontractReconcileIntegration[TerraformInitIntegrationParams]
):
    """Initialize AWS accounts for Terraform usage."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query
        return {
            "accounts": [
                account.dict() for account in self.get_aws_accounts(query_func)
            ],
        }

    def get_aws_accounts(
        self, query_func: Callable, account_name: str | None = None
    ) -> list[AWSAccountV1]:
        """Return all AWS accounts with terraform username."""
        return [
            account
            for account in aws_accounts_query(query_func).accounts or []
            if integration_is_enabled(self.name, account)
            and (not account_name or account.name == account_name)
            and account.terraform_username
        ]

    @staticmethod
    def get_default_tags(gql_api: GqlApi) -> dict[str, str]:
        try:
            return get_settings(gql_api.query).default_tags
        except ValueError:
            # no settings found
            return {}

    @staticmethod
    def render_state_collection(
        template: str,
        bucket_name: str,
        account: AWSAccountV1,
    ) -> str:
        return jinja2.Template(
            template,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        ).render({
            "account_name": account.name,
            "bucket_name": bucket_name,
            "region": account.resources_default_region,
            "timestamp": int(utc_now().timestamp()),
        })

    def reconcile_account(
        self,
        aws_api: AWSApi,
        merge_request_manager: MergeRequestManager,
        dry_run: bool,
        account: AWSAccountV1,
        state_template: str,
        cloudformation_template: str,
        cloudformation_import_template: str,
        default_tags: dict[str, str],
    ) -> None:
        """
        Reconcile the terraform state for a given account.

        Create S3 bucket via CloudFormation and Merge Request to update template file on init.
        Import existing bucket if it exists but not managed by CloudFormation.
        Update CloudFormation stack if tags or template body differ.

        CloudFormation stack name and bucket name is `terraform-<account_name>`.
        `cloudformation_import_template` should be minimal template with identifier fields only.
        `cloudformation_template` should be the full template.
        Use import template to import then update stack to match full template.
        This will ensure imported resources match CloudFormation template.
        And all desired changes in full template are applied.
        Both templates must have BucketName in Parameters.

        Args:
            aws_api: AWSApi: AWS API client for the target account.
            merge_request_manager: MergeRequestManager: Manager to handle merge requests.
            dry_run: bool: If True, do not make any changes.
            account: AWSAccountV1: The AWS account to reconcile.
            state_template: str: Jinja2 template for the Terraform state configuration.
            cloudformation_template: str: CloudFormation template to create the S3 bucket.
            cloudformation_import_template: str: CloudFormation template to import existing S3 bucket.
            default_tags: dict[str, str]: Default tags to apply to the CloudFormation stack.

        Returns:
            None
        """
        bucket_name = (
            account.terraform_state.bucket
            if account.terraform_state
            else f"terraform-{account.name}"
        )

        tags = default_tags | get_aws_account_tags(account.organization)

        if account.terraform_state is None:
            return self._provision_terraform_state(
                aws_api=aws_api,
                merge_request_manager=merge_request_manager,
                dry_run=dry_run,
                account=account,
                bucket_name=bucket_name,
                cloudformation_template=cloudformation_template,
                state_template=state_template,
                tags=tags,
            )

        stack = aws_api.cloudformation.get_stack(stack_name=bucket_name)

        if stack is None:
            return self._import_cloudformation_stack(
                aws_api=aws_api,
                dry_run=dry_run,
                bucket_name=bucket_name,
                cloudformation_import_template=cloudformation_import_template,
                cloudformation_template=cloudformation_template,
                tags=tags,
            )

        return self._reconcile_cloudformation_stack(
            aws_api=aws_api,
            dry_run=dry_run,
            bucket_name=bucket_name,
            cloudformation_template=cloudformation_template,
            tags=tags,
            current_tags={tag["Key"]: tag["Value"] for tag in stack.get("Tags", [])},
        )

    def _provision_terraform_state(
        self,
        aws_api: AWSApi,
        merge_request_manager: MergeRequestManager,
        dry_run: bool,
        account: AWSAccountV1,
        bucket_name: str,
        cloudformation_template: str,
        state_template: str,
        tags: dict[str, str],
    ) -> None:
        logging.info("Creating bucket '%s' for account '%s'", bucket_name, account.name)
        if not dry_run:
            aws_api.cloudformation.create_stack(
                stack_name=bucket_name,
                change_set_name=f"create-{bucket_name}",
                template_body=cloudformation_template,
                parameters={"BucketName": bucket_name},
                tags=tags,
            )
        state_collection = self.render_state_collection(
            template=state_template,
            bucket_name=bucket_name,
            account=account,
        )
        merge_request_manager.create_merge_request(
            data=MrData(
                account=account.name,
                content=state_collection,
                path=f"{self.params.template_collection_root_path}/{account.name}.yml",
            )
        )

    @staticmethod
    def _import_cloudformation_stack(
        aws_api: AWSApi,
        dry_run: bool,
        bucket_name: str,
        cloudformation_import_template: str,
        cloudformation_template: str,
        tags: dict[str, str],
    ) -> None:
        logging.info("Importing existing bucket %s", bucket_name)
        if not dry_run:
            aws_api.cloudformation.create_stack(
                stack_name=bucket_name,
                change_set_name=f"import-{bucket_name}",
                template_body=cloudformation_import_template,
                parameters={"BucketName": bucket_name},
                tags=tags,
            )
            logging.info("Syncing stack %s after import", bucket_name)
            aws_api.cloudformation.update_stack(
                stack_name=bucket_name,
                template_body=cloudformation_template,
                parameters={"BucketName": bucket_name},
                tags=tags,
            )

    @staticmethod
    def _reconcile_cloudformation_stack(
        aws_api: AWSApi,
        dry_run: bool,
        bucket_name: str,
        cloudformation_template: str,
        tags: dict[str, str],
        current_tags: dict[str, str],
    ) -> None:
        if (
            current_tags != tags
            or aws_api.cloudformation.get_template_body(stack_name=bucket_name)
            != cloudformation_template
        ):
            logging.info("Updating stack %s", bucket_name)
            if not dry_run:
                aws_api.cloudformation.update_stack(
                    stack_name=bucket_name,
                    template_body=cloudformation_template,
                    parameters={"BucketName": bucket_name},
                    tags=tags,
                )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        accounts = self.get_aws_accounts(
            gql_api.query, account_name=self.params.account_name
        )
        if not accounts:
            # nothing to do
            return

        vcs = VCS(
            secret_reader=self.secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=False,
            allow_opening_mrs=True,
        )
        if defer:
            defer(vcs.cleanup)
        merge_request_manager = MergeRequestManager(
            vcs=vcs,
            renderer=Renderer(),
            parser=create_parser(),
            auto_merge_enabled=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-auto-merge-mrs", default=False
            ),
        )
        state_template = gql_api.get_resource(path=self.params.state_tmpl_resource)[
            "content"
        ]
        cloudformation_template = gql_api.get_resource(
            path=self.params.cloudformation_template_resource
        )["content"]
        cloudformation_import_template = gql_api.get_resource(
            path=self.params.cloudformation_import_template_resource
        )["content"]
        default_tags = self.get_default_tags(gql_api)

        for account in accounts:
            secret = self.secret_reader.read_all_secret(account.automation_token)
            with AWSApi(
                AWSStaticCredentials(
                    access_key_id=secret["aws_access_key_id"],
                    secret_access_key=secret["aws_secret_access_key"],
                    region=account.resources_default_region,
                )
            ) as account_aws_api:
                self.reconcile_account(
                    aws_api=account_aws_api,
                    merge_request_manager=merge_request_manager,
                    dry_run=dry_run,
                    account=account,
                    state_template=state_template,
                    cloudformation_template=cloudformation_template,
                    cloudformation_import_template=cloudformation_import_template,
                    default_tags=default_tags,
                )
