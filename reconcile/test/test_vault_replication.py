import pytest

import reconcile.vault_replication as integ
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigsQueryData,
    JenkinsConfigV1_JenkinsConfigV1,
    JenkinsInstanceV1,
    ResourceV1,
)

from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultInstanceV1,
    VaultInstanceAuthApproleV1,
    VaultInstanceAuthV1,
)

import reconcile.gql_definitions.vault_policies.vault_policies as vault_policies

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.vault import VaultClient


def test_policy_contais_path():
    policy_paths = ["path1", "path2"]
    path = "path1"
    assert integ.policy_contains_path(path, policy_paths) is True


def test_policy_contais_path_false():
    policy_paths = ["path2", "path3"]
    path = "path1"
    assert integ.policy_contains_path(path, policy_paths) is False


def test_check_invalid_paths_ko():
    path_list = ["path1", "path3"]
    policy_paths = ["path1", "path2"]
    with pytest.raises(integ.VaultInvalidPaths):
        integ.check_invalid_paths(path_list, policy_paths)


def test_check_invalid_paths_ok():
    path_list = ["path1", "path2"]
    policy_paths = ["path1", "path2"]
    integ.check_invalid_paths(path_list, policy_paths)


def test_list_invalid_paths():
    path_list = ["path1", "path3"]
    policy_paths = ["path1", "path2"]
    assert integ.list_invalid_paths(path_list, policy_paths) == ["path3"]


@pytest.fixture
def jenkins_config_query_data() -> JenkinsConfigsQueryData:
    return JenkinsConfigsQueryData(
        jenkins_configs=[
            JenkinsConfigV1_JenkinsConfigV1(
                name="jenkins-secrets-config",
                instance=JenkinsInstanceV1(
                    name="jenkins-instance",
                    serverUrl="https://test.net",
                    token=VaultSecret(
                        path="secret_path",
                        field="secret_field",
                        version=None,
                        format=None,
                    ),
                    deleteMethod=None,
                ),
                type="secrets",
                config=None,
                config_path=ResourceV1(
                    content="name: 'test_data_name'\n    secret-path: 'this/is/a/path'"
                ),
            ),
        ]
    )


def test_get_jenkins_secret_list_w_content(
    jenkins_config_query_data: JenkinsConfigsQueryData,
):
    assert integ.get_jenkins_secret_list(
        None, "jenkins-instance", jenkins_config_query_data
    ) == [
        "this/is/a/path",
    ]


@pytest.fixture
def vault_instance_data() -> VaultInstanceV1:
    return VaultInstanceV1(
        name="vault-instance",
        address="https://vault-instance.com",
        auth=VaultInstanceAuthApproleV1(
            provider="approle",
            secretEngine="kv_v1",
            roleID=VaultSecret(
                path="secret/path/vault",
                field="id",
                version=None,
                format=None,
            ),
            secretID=VaultSecret(
                path="secret/path/vault",
                field="secret",
                version=None,
                format=None,
            ),
        ),
        replication=None,
    )


@pytest.fixture
def vault_instance_data_invalid_auth() -> VaultInstanceV1:
    return VaultInstanceV1(
        name="vault-instance",
        address="https://vault-instance.com",
        auth=VaultInstanceAuthV1(
            provider="approle",
            secretEngine="kv_v1",
        ),
        replication=None,
    )


@pytest.fixture(autouse=True)
def reset_singletons():
    VaultClient._instance = None


def test_get_vault_credentials_invalid_auth_method(
    vault_instance_data_invalid_auth: VaultInstanceV1, mocker
):

    mock_vault_client = mocker.patch(
        "reconcile.utils.vault._VaultClient", autospec=True
    )
    mock_vault_client.return_value.read.side_effect = ["a", "b"]

    with pytest.raises(integ.VaultInvalidAuthMethod):
        integ.get_vault_credentials(vault_instance_data_invalid_auth)


def test_get_vault_credentials_app_role(vault_instance_data: VaultInstanceV1, mocker):

    mock_vault_client = mocker.patch(
        "reconcile.utils.vault._VaultClient", autospec=True
    )
    mock_vault_client.return_value.read.side_effect = ["a", "b"]

    assert integ.get_vault_credentials(vault_instance_data) == {
        "role_id": "a",
        "secret_id": "b",
        "server": "https://vault-instance.com",
    }


@pytest.fixture
def policy_query_data() -> vault_policies.VaultPoliciesQueryData:
    return vault_policies.VaultPoliciesQueryData(
        policy=[
            vault_policies.VaultPolicyV1(
                name="test-policy",
                instance=vault_policies.VaultInstanceV1(name="vault-instance"),
                rules='path "this/is/a/path/*" {\n  capabilities = ["create", "read", "update"]\n}\n',
            )
        ]
    )


def test_get_policy_paths(policy_query_data: vault_policies.VaultPoliciesQueryData):
    assert integ.get_policy_paths(
        "test-policy", "vault-instance", policy_query_data
    ) == ["this/is/a/path/*"]
