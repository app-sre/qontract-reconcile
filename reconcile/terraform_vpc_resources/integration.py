import logging
import sys
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

import jinja2

from reconcile.gql_definitions.fragments.aws_vpc_request import (
    AWSAccountV1,
    VPCRequest,
)
from reconcile.status import ExitCodes
from reconcile.terraform_vpc_resources.merge_request import Renderer, create_parser
from reconcile.terraform_vpc_resources.merge_request_manager import (
    MergeRequestManager,
    MrData,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.aws_vpc_requests import get_aws_vpc_requests
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript_aws_client import TerrascriptClient
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "terraform_vpc_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtvr"
AWS_PROVIDER_VERSION = "5.7.1"


class TerraformVpcResourcesParams(PydanticRunParams):
    account_name: str | None
    print_to_file: str | None
    thread_pool_size: int
    enable_deletion: bool = False


class TerraformVpcResources(QontractReconcileIntegration[TerraformVpcResourcesParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION.replace("_", "-")

    def _filter_accounts(
        self, data: Iterable[VPCRequest], account_name: str | None
    ) -> list[AWSAccountV1]:
        """Return a list of accounts extracted from the provided VPCRequests.
        If account_name is given returns the account object with that name."""
        accounts = [vpc.account for vpc in data]

        if account_name:
            accounts = [account for account in accounts if account.name == account_name]

        return accounts

    def _handle_outputs(
        self, requests: Iterable[VPCRequest], outputs: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Receives a terraform outputs dict and returns a map of outputs per VPC requests"""
        outputs_per_request: MutableMapping[str, Any] = {}
        for request in requests:
            # Skiping requests that don't have outputs,
            # this happens because we are not filtering the requests
            # when running the integration for a single account with --account-name.
            # We also don't want to create outputs for deleted requets.
            if request.account.name not in outputs.keys() or request.delete:
                continue

            outputs_per_request[request.identifier] = []

            outputs_per_account = outputs[request.account.name]

            # If the output exists for that request get its value
            # Else get None
            private_subnets = outputs_per_account.get(
                f"{request.identifier}-private_subnets", {}
            ).get("value", [])
            public_subnets = outputs_per_account.get(
                f"{request.identifier}-public_subnets", {}
            ).get("value", [])

            values = {
                "static": {
                    "vpc_id": outputs_per_account.get(
                        f"{request.identifier}-vpc_id", {}
                    ).get("value"),
                    "subnets": {
                        "private": private_subnets,
                        "public": public_subnets,
                    },
                    "account_name": request.account.name,
                    "region": request.region,
                    "cidr_block": request.cidr_block.network_address,
                    "identifier": request.identifier,
                }
            }

            outputs_per_request[request.identifier] = values

        return outputs_per_request

    def _render_template(self, template: str, data: Mapping[str, Any]) -> str:
        return jinja2.Template(
            template,
            undefined=jinja2.StrictUndefined,
            trim_blocks=False,
            lstrip_blocks=False,
            keep_trailing_newline=False,
        ).render(data)

    def run(self, dry_run: bool) -> None:
        account_name = self.params.account_name
        thread_pool_size = self.params.thread_pool_size
        enable_deletion = self.params.enable_deletion

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        gql_api = gql.get_api()
        data = get_aws_vpc_requests(gql_api=gql_api)

        if data:
            accounts = self._filter_accounts(data, account_name)
            if account_name and not accounts:
                msg = f"The account {account_name} doesn't have any managed vpc. Verify your input"
                logging.debug(msg)
                sys.exit(ExitCodes.SUCCESS)
        else:
            logging.debug("No VPC requests found, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)

        accounts_untyped: list[dict] = [acc.dict(by_alias=True) for acc in accounts]
        with TerrascriptClient(
            integration=QONTRACT_INTEGRATION,
            integration_prefix=QONTRACT_TF_PREFIX,
            thread_pool_size=thread_pool_size,
            accounts=accounts_untyped,
            secret_reader=secret_reader,
        ) as ts_client:
            ts_client.populate_vpc_requests(data, AWS_PROVIDER_VERSION)

        working_dirs = ts_client.dump(print_to_file=self.params.print_to_file)

        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)

        tf_client = TerraformClient(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            integration_prefix=QONTRACT_TF_PREFIX,
            accounts=accounts_untyped,
            working_dirs=working_dirs,
            thread_pool_size=thread_pool_size,
        )

        tf_client.safe_plan(enable_deletion=enable_deletion)

        if dry_run:
            sys.exit(ExitCodes.SUCCESS)

        tf_client.apply()

        tf_client.init_outputs()

        handled_output = self._handle_outputs(data, tf_client.outputs)

        # MR and template Management
        vcs = VCS(
            secret_reader=secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=False,
            allow_opening_mrs=True,
        )

        mr_manager = MergeRequestManager(
            vcs=vcs,
            renderer=Renderer(),
            parser=create_parser(),
            auto_merge_enabled=True,
        )

        mr_manager._fetch_managed_open_merge_requests()

        # Create a MR for each vpc request if the MR don't exist yet
        for _, outputs in handled_output.items():
            template = gql_api.get_template(
                path="/templating/templates/terraform-vpc-resources/vpc.yml"
            )["template"]
            content = self._render_template(template=template, data=outputs)

            mr_manager.create_merge_request(
                MrData(
                    account=outputs["static"]["account_name"],
                    content=content,
                    path=f"data/aws/{outputs['static']['account_name']}/vpcs/{outputs['static']['identifier']}.yml",
                )
            )

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="account_name",
            shard_path_selectors={
                "accounts[*].name",
            },
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )
