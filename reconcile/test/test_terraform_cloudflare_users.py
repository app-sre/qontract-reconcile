from typing import Any
from unittest.mock import (
    call,
    mock_open,
)

import pytest

from reconcile import terraform_cloudflare_users
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_cloudflare_users.app_interface_setting_cloudflare_and_vault import (
    AppInterfaceSettingCloudflareAndVaultQueryData,
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.terraform_cloudflare_users.terraform_cloudflare_roles import (
    AWSAccountV1,
    AWSTerraformStateIntegrationsV1,
    CloudflareAccountRoleQueryData,
    CloudflareAccountRoleV1,
    CloudflareAccountV1,
    RoleV1,
    TerraformStateAWSV1,
    UserV1,
)
from reconcile.terraform_cloudflare_users import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
    QONTRACT_TF_PREFIX,
    CloudflareUser,
    TerraformCloudflareUsersParams,
    build_external_resource_spec_from_cloudflare_users,
    get_cloudflare_users,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.secret_reader import SecretReaderBase


@pytest.fixture
def query_data_with_one_role_one_user():
    return CloudflareAccountRoleQueryData(
        cloudflare_account_roles=[
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator",
                roles=["Administrator"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds", field="some-field", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account",
                        automationToken=VaultSecret(
                            path="some-path",
                            field="some-field",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            )
        ]
    )


@pytest.fixture
def query_data_with_one_role_two_users():
    return CloudflareAccountRoleQueryData(
        cloudflare_account_roles=[
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator",
                roles=["Administrator"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            ),
                            UserV1(
                                org_username="user2", cloudflare_user="user2@redhat.com"
                            ),
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds", field="some-field", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account",
                        automationToken=VaultSecret(
                            path="some-path",
                            field="some-field",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            )
        ]
    )


@pytest.fixture
def query_data_with_two_roles_from_same_account_one_user():
    return CloudflareAccountRoleQueryData(
        cloudflare_account_roles=[
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator",
                roles=["Administrator"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds", field="some-field", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account",
                        automationToken=VaultSecret(
                            path="some-path",
                            field="some-field",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator-read-only",
                roles=["Administrator Read Only"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds", field="some-field", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account",
                        automationToken=VaultSecret(
                            path="some-path",
                            field="some-field",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_with_two_roles_from_different_account_one_user():
    return CloudflareAccountRoleQueryData(
        cloudflare_account_roles=[
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator",
                roles=["Administrator"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account-1",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds-1", field="some-field-1", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account-1",
                        automationToken=VaultSecret(
                            path="some-path-1",
                            field="some-field-1",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator-read-only",
                roles=["Administrator Read Only"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account-2",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds-2", field="some-field-2", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account-2",
                        automationToken=VaultSecret(
                            path="some-path-2",
                            field="some-field-2",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_with_two_roles_from_different_account_two_users():
    return CloudflareAccountRoleQueryData(
        cloudflare_account_roles=[
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator",
                roles=["Administrator"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user1", cloudflare_user="user1@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account-1",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds-1", field="some-field-1", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account-1",
                        automationToken=VaultSecret(
                            path="some-path-1",
                            field="some-field-1",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
            CloudflareAccountRoleV1(
                name="cloudflare-account-administrator-read-only",
                roles=["Administrator Read Only"],
                access_roles=[
                    RoleV1(
                        users=[
                            UserV1(
                                org_username="user2", cloudflare_user="user2@redhat.com"
                            )
                        ]
                    )
                ],
                account=CloudflareAccountV1(
                    name="cloudflare-account-2",
                    providerVersion="3.19",
                    apiCredentials=VaultSecret(
                        path="creds-2", field="some-field-2", version=None, format=None
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="aws-account-2",
                        automationToken=VaultSecret(
                            path="some-path-2",
                            field="some-field-2",
                            version=None,
                            format=None,
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-users",
                                    key="some-key.tfstate",
                                )
                            ],
                        ),
                    ),
                    enforceTwofactor=True,
                    type="enterprise",
                ),
            ),
        ]
    )


@pytest.fixture
def app_interface_settings_cloudflare_and_vault():
    return AppInterfaceSettingCloudflareAndVaultQueryData(
        settings=[
            AppInterfaceSettingsV1(
                cloudflareEmailDomainAllowList=["redhat.com"], vault=True
            )
        ]
    )


def secret_reader_side_effect(*args):
    if {
        "path": "some-path",
        "field": "some-field",
        "version": None,
        "q_format": None,
    } == args[0]:
        aws_acct_creds = {}
        aws_acct_creds["aws_access_key_id"] = "key_id"
        aws_acct_creds["aws_secret_access_key"] = "access_key"
        return aws_acct_creds
    elif {
        "path": "creds",
        "field": "some-field",
        "version": None,
        "q_format": None,
    } == args[0]:
        cf_acct_creds = {}
        cf_acct_creds["api_token"] = "api_token"
        cf_acct_creds["account_id"] = "account_id"
        return cf_acct_creds


@pytest.fixture
def secret_reader(mocker):
    secret_reader = mocker.Mock(spec=SecretReaderBase)
    secret_reader.read_all_secret.side_effect = secret_reader_side_effect

    mocked_secret_reader = mocker.patch(
        "reconcile.terraform_cloudflare_users.create_secret_reader", autospec=True
    )
    mocked_secret_reader.return_value = secret_reader

    return mocked_secret_reader


def test_terraform_cloudflare_users(
    mocker,
    secret_reader,
    query_data_with_one_role_one_user,
    app_interface_settings_cloudflare_and_vault,
):

    # Used to mock out file system dependency within TerrascriptCloudflareClient
    mock_builtins_open = mock_open()
    mocker.patch("builtins.open", mock_builtins_open)
    patch_mkdtemp = mocker.patch("tempfile.mkdtemp")
    tf_directory = "/tmp/test"
    patch_mkdtemp.return_value = tf_directory

    mocker.patch("reconcile.terraform_cloudflare_users.gql", autospec=True)

    query_data = mocker.patch(
        "reconcile.terraform_cloudflare_users.terraform_cloudflare_roles", autospec=True
    )

    query_data.query.return_value = query_data_with_one_role_one_user

    settings = mocker.patch(
        "reconcile.terraform_cloudflare_users.app_interface_setting_cloudflare_and_vault",
        autospec=True,
    )
    settings.query.return_value = app_interface_settings_cloudflare_and_vault

    mocked_terraform_client = mocker.patch(
        "reconcile.terraform_cloudflare_users.TerraformClient", autospec=True
    )
    mocked_terraform_client.return_value.plan.return_value = False, None
    params = TerraformCloudflareUsersParams(
        print_to_file=None,
        account_name="cloudflare-account",
        thread_pool_size=20,
        enable_deletion=True,
    )
    dry_run = True
    integration = terraform_cloudflare_users.TerraformCloudflareUsers(params=params)

    integration.run(dry_run)

    expected_call_args = call(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        [
            {
                "name": "cloudflare-account",
                "providerVersion": "3.19",
                "apiCredentials": {
                    "path": "creds",
                    "field": "some-field",
                    "version": None,
                    "format": None,
                },
                "terraformStateAccount": {
                    "name": "aws-account",
                    "automationToken": {
                        "path": "some-path",
                        "field": "some-field",
                        "version": None,
                        "format": None,
                    },
                    "terraformState": {
                        "provider": "s3",
                        "bucket": "app-interface",
                        "region": "us-east-1",
                        "integrations": [
                            {
                                "integration": "terraform-cloudflare-users",
                                "key": "some-key.tfstate",
                            }
                        ],
                    },
                },
                "enforceTwofactor": True,
                "type": "enterprise",
            }
        ],
        {"cloudflare-account": tf_directory},
        params.thread_pool_size,
    )
    assert mocked_terraform_client.called
    assert mocked_terraform_client.call_args == expected_call_args
    assert call().apply() not in mocked_terraform_client.method_calls


def test_get_cloudflare_users_without_email_domain_allow_list(
    query_data_with_one_role_one_user,
):
    actual_users = get_cloudflare_users(
        query_data_with_one_role_one_user.cloudflare_account_roles, None, None
    )
    expected_users: dict[str, dict[str, Any]] = {}
    assert actual_users == expected_users


def test_get_cloudflare_users_with_one_role_one_user(query_data_with_one_role_one_user):
    actual_users = get_cloudflare_users(
        query_data_with_one_role_one_user.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )
    expected_users = {
        "cloudflare-account": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account",
                org_username="user1",
                roles={"Administrator"},
            )
        }
    }
    assert actual_users == expected_users


def test_get_cloudflare_users_with_one_role_two_users(
    query_data_with_one_role_two_users,
):
    actual_users = get_cloudflare_users(
        query_data_with_one_role_two_users.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )
    expected_users = {
        "cloudflare-account": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account",
                org_username="user1",
                roles={"Administrator"},
            ),
            "user2@redhat.com": CloudflareUser(
                email_address="user2@redhat.com",
                account_name="cloudflare-account",
                org_username="user2",
                roles={"Administrator"},
            ),
        }
    }
    assert actual_users == expected_users


def test_get_cloudflare_users_with_two_roles_from_same_account_one_user(
    query_data_with_two_roles_from_same_account_one_user,
):
    actual_users = get_cloudflare_users(
        query_data_with_two_roles_from_same_account_one_user.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )

    expected_users = {
        "cloudflare-account": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account",
                org_username="user1",
                roles={"Administrator", "Administrator Read Only"},
            )
        }
    }
    assert actual_users == expected_users


def test_get_cloudflare_users_with_two_roles_from_different_account_one_user(
    query_data_with_two_roles_from_different_account_one_user,
):
    actual_users = get_cloudflare_users(
        query_data_with_two_roles_from_different_account_one_user.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )

    expected_users = {
        "cloudflare-account-1": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account-1",
                org_username="user1",
                roles={"Administrator"},
            )
        },
        "cloudflare-account-2": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account-2",
                org_username="user1",
                roles={"Administrator Read Only"},
            )
        },
    }

    assert actual_users == expected_users


def test_external_spec_with_two_roles_from_different_account_one_user(
    query_data_with_two_roles_from_different_account_two_users,
):
    actual_users = get_cloudflare_users(
        query_data_with_two_roles_from_different_account_two_users.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )

    print(actual_users)
    expected_users = {
        "cloudflare-account-1": {
            "user1@redhat.com": CloudflareUser(
                email_address="user1@redhat.com",
                account_name="cloudflare-account-1",
                org_username="user1",
                roles={"Administrator"},
            )
        },
        "cloudflare-account-2": {
            "user2@redhat.com": CloudflareUser(
                email_address="user2@redhat.com",
                account_name="cloudflare-account-2",
                org_username="user2",
                roles={"Administrator Read Only"},
            )
        },
    }

    assert actual_users == expected_users


def test_build_external_resource_spec_from_cloudflare_users(
    query_data_with_two_roles_from_same_account_one_user,
):

    users = get_cloudflare_users(
        query_data_with_two_roles_from_same_account_one_user.cloudflare_account_roles,
        None,
        ["redhat.com"],
    )

    actual_specs = build_external_resource_spec_from_cloudflare_users(users)

    expected_spec = ExternalResourceSpec(
        provision_provider="cloudflare",
        provisioner={"name": "cloudflare-account"},
        resource={
            "provider": "account_member",
            "identifier": "user1",
            "email_address": "user1@redhat.com",
            "account_id": "${var.account_id}",
            "role_ids": [
                '%{ for role in data.cloudflare_account_roles.cloudflare-account.roles ~}  %{if role.name == "Administrator" ~}${role.id}%{ endif ~}  %{ endfor ~}',
                '%{ for role in data.cloudflare_account_roles.cloudflare-account.roles ~}  %{if role.name == "Administrator Read Only" ~}${role.id}%{ endif ~}  %{ endfor ~}',
            ],
            "cloudflare_account_roles": {
                "identifier": "cloudflare-account",
                "account_id": "${var.account_id}",
            },
        },
        namespace={},
    )

    count = 0
    for spec in actual_specs:
        count += 1
        actual_spec = spec

    assert count == 1

    # Doing comparison manual way as resource.role_ids is a set of unique values which is not taken into consideration
    # while using equal(==) comparison operator with pure dictionary
    assert actual_spec.provision_provider == expected_spec.provision_provider
    assert actual_spec.provisioner == expected_spec.provisioner
    assert actual_spec.namespace == expected_spec.namespace
    assert actual_spec.secret == expected_spec.secret

    actual_resource = actual_spec.resource
    expected_resource = expected_spec.resource

    actual_role_ids = actual_resource.pop("role_ids")
    expected_role_ids = expected_resource.pop("role_ids")

    assert actual_resource == expected_resource

    assert set(actual_role_ids) == set(expected_role_ids)
