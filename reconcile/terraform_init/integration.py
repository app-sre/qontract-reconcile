import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import jinja2

from reconcile.gql_definitions.terraform_init.aws_accounts import AWSAccountV1
from reconcile.gql_definitions.terraform_init.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.terraform_init.merge_request import Renderer, create_parser
from reconcile.terraform_init.merge_request_manager import MergeRequestManager, MrData
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
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
    state_tmpl_resource: str = "/terraform-init/terraform-state.yml"
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
        """Return all AWS accounts with terraform username but no terraform state set."""
        return [
            account
            for account in aws_accounts_query(query_func).accounts or []
            if integration_is_enabled(self.name, account)
            and (not account_name or account.name == account_name)
            and account.terraform_username
            and not account.terraform_state
        ]

    def render_state_collection(
        self, template: str, bucket_name: str, account: AWSAccountV1
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
            "timestamp": int(datetime.now(tz=UTC).timestamp()),
        })

    def reconcile_account(
        self,
        account_aws_api: AWSApi,
        merge_request_manager: MergeRequestManager,
        dry_run: bool,
        state_collection: str,
        bucket_name: str,
        account: AWSAccountV1,
    ) -> None:
        logging.info("Creating bucket '%s' for account '%s'", bucket_name, account.name)
        if not dry_run:
            # the creation of the bucket is idempotent
            account_aws_api.s3.create_bucket(
                name=bucket_name, region=account.resources_default_region
            )
        merge_request_manager.create_merge_request(
            data=MrData(
                account=account.name,
                content=state_collection,
                path=f"{self.params.template_collection_root_path}/{account.name}.yml",
            )
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
        for account in accounts:
            secret = self.secret_reader.read_all_secret(account.automation_token)
            with AWSApi(
                AWSStaticCredentials(
                    access_key_id=secret["aws_access_key_id"],
                    secret_access_key=secret["aws_secret_access_key"],
                    region=account.resources_default_region,
                )
            ) as account_aws_api:
                bucket_name = f"terraform-{account.name}"
                state_collection = self.render_state_collection(
                    state_template, bucket_name, account
                )
                self.reconcile_account(
                    account_aws_api,
                    merge_request_manager,
                    dry_run,
                    state_collection,
                    bucket_name,
                    account,
                )
