import sys
from dataclasses import dataclass
from typing import (
    Any,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Set,
    Tuple,
)

from reconcile.gql_definitions.terraform_cloudflare_users import (
    app_interface_setting_cloudflare_and_vault,
    terraform_cloudflare_roles,
)
from reconcile.gql_definitions.terraform_cloudflare_users.app_interface_setting_cloudflare_and_vault import (
    AppInterfaceSettingCloudflareAndVaultQueryData,
)
from reconcile.gql_definitions.terraform_cloudflare_users.terraform_cloudflare_roles import (
    CloudflareAccountRoleQueryData,
    CloudflareAccountRoleV1,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.runtime.integration import QontractReconcileIntegration
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform import safe_resource_id
from reconcile.utils.terraform.config_client import (
    ClientAlreadyRegisteredError,
    TerraformConfigClientCollection,
)
from reconcile.utils.terraform_client import run_terraform
from reconcile.utils.terrascript.cloudflare_client import (
    AccountShardingStrategy,
    IntegrationUndefined,
    InvalidTerraformState,
    TerrascriptCloudflareClientFactory,
)
from reconcile.utils.terrascript.models import (
    CloudflareAccount,
    Integration,
    TerraformStateS3,
    VaultSecret,
)

QONTRACT_INTEGRATION = "terraform_cloudflare_users"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcfusers"
CLOUDFLARE_EMAIL_DOMAIN_ALLOW_LIST_KEY = "cloudflareEmailDomainAllowList"


@dataclass
class CloudflareUser:
    email_address: str
    account_name: str
    org_username: str
    roles: Set[str]


class TerraformCloudflareUsers(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION.replace("_", "-")

    def get_early_exit_desired_state(
        self, *args: Any, **kwargs: Any
    ) -> Optional[dict[str, Any]]:

        cloudflare_roles, settings = self._get_desired_state()

        return {
            "cloudflare_roles": cloudflare_roles.dict(),
            CLOUDFLARE_EMAIL_DOMAIN_ALLOW_LIST_KEY: settings.settings[0]
            if settings.settings is not None
            else [],
        }

    def _get_desired_state(
        self,
    ) -> Tuple[
        CloudflareAccountRoleQueryData, AppInterfaceSettingCloudflareAndVaultQueryData
    ]:
        cloudflare_roles = terraform_cloudflare_roles.query(
            query_func=gql.get_api().query
        )

        settings = app_interface_setting_cloudflare_and_vault.query(
            query_func=gql.get_api().query
        )
        return cloudflare_roles, settings

    def run(self, dry_run: bool, *args: Any, **kwargs: Any) -> None:
        print_to_file = args[0]
        account_name = args[1]
        thread_pool_size = args[2]
        enable_deletion = args[3]

        cloudflare_roles, settings = self._get_desired_state()

        secret_reader = create_secret_reader(
            use_vault=settings.settings[0].vault
            if settings.settings is not None
            else True
        )

        cf_clients = self._build_cloudflare_terraform_config_client_collection(
            cloudflare_roles, secret_reader, account_name
        )

        users = get_cloudflare_users(
            cloudflare_roles.cloudflare_account_roles,
            account_name,
            settings.settings[0].cloudflare_email_domain_allow_list
            if settings.settings is not None
            else None,
        )
        specs = build_external_resource_spec_from_cloudflare_users(users)

        cf_clients.add_specs(specs)
        cf_clients.populate_resources()

        working_dirs = cf_clients.dump(print_to_file=print_to_file)

        if print_to_file:
            return

        # for storing unique CloudflareAccountV1 since cloudflare_account_role_v1 can contain duplicates due to schema
        account_names_to_account = {
            role.account.name: role.account
            for role in cloudflare_roles.cloudflare_account_roles or []
            if role.account.name in cf_clients.dump()
        }

        accounts = [
            acct.dict(by_alias=True) for _, acct in account_names_to_account.items()
        ]

        run_terraform(
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            QONTRACT_TF_PREFIX,
            dry_run,
            enable_deletion,
            thread_pool_size,
            working_dirs,
            accounts,
        )

    def _build_cloudflare_terraform_config_client_collection(
        self,
        query_data: CloudflareAccountRoleQueryData,
        secret_reader: SecretReaderBase,
        account_name: str,
    ) -> TerraformConfigClientCollection:
        cf_clients = TerraformConfigClientCollection()
        for role in query_data.cloudflare_account_roles or []:
            if account_name and role.account.name != account_name:
                continue
            cf_account = CloudflareAccount(
                role.account.name,
                VaultSecret(
                    role.account.api_credentials.path,
                    role.account.api_credentials.field,
                    role.account.api_credentials.version,
                    role.account.api_credentials.q_format,
                ),
                role.account.enforce_twofactor,
                role.account.q_type,
                role.account.provider_version,
            )

            tf_state = role.account.terraform_state_account.terraform_state
            if not tf_state:
                raise ValueError(
                    f"AWS account {role.account.terraform_state_account.name} cannot be used for Cloudflare "
                    f"account {cf_account.name} because it does define a terraform state "
                )

            bucket = tf_state.bucket
            region = tf_state.region
            integrations = tf_state.integrations

            if not bucket:
                raise InvalidTerraformState("Terraform state must have bucket defined")
            if not region:
                raise InvalidTerraformState("Terraform state must have region defined")

            integration = None
            for i in integrations:
                if i.integration.replace("-", "_") == QONTRACT_INTEGRATION:
                    integration = i
                    break

            if not integration:
                raise IntegrationUndefined(
                    "Must declare integration name under terraform state in app-interface"
                )

            tf_state_s3 = TerraformStateS3(
                VaultSecret(
                    role.account.terraform_state_account.automation_token.path,
                    role.account.terraform_state_account.automation_token.field,
                    role.account.terraform_state_account.automation_token.version,
                    role.account.terraform_state_account.automation_token.q_format,
                ),
                bucket,
                region,
                Integration(integration.integration, integration.key),
            )

            client = TerrascriptCloudflareClientFactory.get_client(
                tf_state_s3,
                cf_account,
                AccountShardingStrategy(cf_account),
                secret_reader,
                True,
            )

            try:
                cf_clients.register_client(cf_account.name, client)
            except ClientAlreadyRegisteredError:
                pass

        return cf_clients


def get_cloudflare_users(
    cloudflare_roles: Optional[Iterable[CloudflareAccountRoleV1]],
    account_name: Optional[str],
    email_domain_allow_list: Optional[Iterable[str]],
) -> Mapping[str, Mapping[str, CloudflareUser]]:
    """
    Builds a two-level dictionary of users with 1st level keys mapping to cloudflare account names
    and 2nd level keys mapping to user's email address.
    The method also takes into consideration account_name and email_domain_allow_list which can be
    used to filter users not matching these parameters
    """
    users: dict[str, dict[str, CloudflareUser]] = {}

    for cf_role in cloudflare_roles or []:
        if account_name and cf_role.account.name != account_name:
            continue
        for access_role in cf_role.access_roles or []:
            for user in access_role.users:
                if user.cloudflare_user is not None and (
                    user.cloudflare_user.split("@")[1]
                    in (email_domain_allow_list or [])
                ):
                    temp = users.get(cf_role.account.name)
                    if temp is not None:
                        if temp.get(user.cloudflare_user) is not None:
                            users[cf_role.account.name][
                                user.cloudflare_user
                            ].roles.update(set(cf_role.roles))
                        else:
                            users[cf_role.account.name][
                                user.cloudflare_user
                            ] = CloudflareUser(
                                user.cloudflare_user,
                                cf_role.account.name,
                                user.org_username,
                                set(cf_role.roles),
                            )

                    else:
                        users[cf_role.account.name] = {
                            user.cloudflare_user: CloudflareUser(
                                user.cloudflare_user,
                                cf_role.account.name,
                                user.org_username,
                                set(cf_role.roles),
                            )
                        }

    return users


def build_external_resource_spec_from_cloudflare_users(
    cloudflare_users: Mapping[str, Mapping[str, CloudflareUser]]
) -> Iterable[ExternalResourceSpec]:
    specs: list[ExternalResourceSpec] = []

    for _, v in cloudflare_users.items():
        for _, cf_user in v.items():
            data_source_cloudflare_account_roles = {
                "identifier": safe_resource_id(cf_user.account_name),
                "account_id": "${var.account_id}",
            }

            cloudflare_account_member = {
                "provider": "cloudflare_account_member",
                "identifier": safe_resource_id(cf_user.org_username),
                "email_address": cf_user.email_address,
                "account_id": "${var.account_id}",
                "role_ids": [
                    # I know this is ugly :(
                    f'%{{ for role in data.cloudflare_account_roles.{safe_resource_id(cf_user.account_name)}.roles ~}}  %{{if role.name == "{each}" ~}}${{role.id}}%{{ endif ~}}  %{{ endfor ~}}'
                    for each in cf_user.roles
                ],
                "cloudflare_account_roles": data_source_cloudflare_account_roles,
            }
            specs.append(
                _get_external_spec_from_resource(
                    cloudflare_account_member, cf_user.account_name
                )
            )

    return specs


def _get_external_spec_from_resource(
    resource: MutableMapping[Any, Any], account_name: str
) -> ExternalResourceSpec:
    return ExternalResourceSpec(
        provision_provider="cloudflare",
        provisioner={"name": f"{account_name}"},
        namespace={},
        resource=resource,
    )
