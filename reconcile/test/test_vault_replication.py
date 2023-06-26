from typing import cast

import pytest

import reconcile.vault_replication as integ
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigsQueryData,
    JenkinsConfigV1_JenkinsConfigV1,
    JenkinsInstanceV1,
    ResourceV1,
)
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultReplicationConfigV1_VaultInstanceAuthV1,
    VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
)
from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.test.fixtures import Fixtures
from reconcile.utils.vault import (
    SecretAccessForbidden,
    SecretNotFound,
    SecretVersionNotFound,
    VaultClient,
    _VaultClient,
)

fxt = Fixtures("vault_replication")


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


@pytest.fixture
def vault_instance_data_invalid_auth() -> VaultReplicationConfigV1_VaultInstanceAuthV1:
    return VaultReplicationConfigV1_VaultInstanceAuthV1(
        provider="test",
        secretEngine="kv_v1",
    )


@pytest.fixture(autouse=True)
def reset_singletons():
    VaultClient._instance = None


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


def test_policy_contais_path():
    policy_paths = ["path1", "path2"]
    path = "path1"
    assert integ._policy_contains_path(path, policy_paths) is True


def test_policy_contais_path_false():
    policy_paths = ["path2", "path3"]
    path = "path1"
    assert integ._policy_contains_path(path, policy_paths) is False


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
def vault_client_test() -> _VaultClient:
    return cast(_VaultClient, None)


def test_get_jenkins_secret_list_w_content(
    jenkins_config_query_data: JenkinsConfigsQueryData,
    vault_client_test: _VaultClient,
):
    assert integ.get_jenkins_secret_list(
        vault_client_test, "jenkins-instance", jenkins_config_query_data
    ) == [
        "this/is/a/path",
    ]


@pytest.fixture
def vault_instance_data() -> (
    VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1
):
    return VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1(
        provider="approle",
        secretEngine="kv_v1",
        roleID=VaultSecret(
            path="secret/path/role_id",
            field="role_id",
            version=None,
            format=None,
        ),
        secretID=VaultSecret(
            path="secret/path/secret_id",
            field="secret_id",
            version=None,
            format=None,
        ),
    )


def test_get_vault_credentials_invalid_auth_method(
    vault_instance_data_invalid_auth: VaultReplicationConfigV1_VaultInstanceAuthV1,
    mocker,
):
    mock_vault_client = mocker.patch(
        "reconcile.utils.vault._VaultClient", autospec=True
    )
    mock_vault_client.return_value.read.side_effect = ["a", "b"]

    with pytest.raises(integ.VaultInvalidAuthMethod):
        integ.get_vault_credentials(
            vault_instance_data_invalid_auth, "http://vault.com"
        )


def test_get_vault_credentials_app_role(
    vault_instance_data: VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    mocker,
):
    mock_vault_client = mocker.patch(
        "reconcile.utils.vault._VaultClient", autospec=True
    )
    mock_vault_client.return_value.read.side_effect = ["a", "b"]

    assert integ.get_vault_credentials(
        vault_instance_data, "https://vault-instance.com"
    ) == {
        "role_id": "a",
        "secret_id": "b",
        "server": "https://vault-instance.com",
    }


def test_get_policy_paths(policy_query_data: vault_policies.VaultPoliciesQueryData):
    assert integ.get_policy_paths(
        "test-policy", "vault-instance", policy_query_data
    ) == ["this/is/a/path/*"]


@pytest.mark.parametrize(
    "path, vault_list, return_value",
    [
        (
            "app-sre/test/path/{template}-1",
            [
                "app-sre/test/path/test-1",
                "app-sre/test/path/test-2",
                "app-sre/example/path/test-1",
            ],
            ["app-sre/test/path/test-1"],
        ),
        (
            "app-sre/test/path/{template}",
            [
                "app-sre/test/path/test-1",
                "app-sre/test/path/test-2",
                "app-sre/example/path/test-1",
            ],
            ["app-sre/test/path/test-1", "app-sre/test/path/test-2"],
        ),
        (
            "app-sre/{template}/path/{template}",
            [
                "app-sre/test/path/test-1",
                "app-sre/test/path/test-2",
                "app-sre/example/path/test-1",
                "app-sre/example/path2/test-1",
            ],
            [
                "app-sre/test/path/test-1",
                "app-sre/test/path/test-2",
                "app-sre/example/path/test-1",
            ],
        ),
        (
            "app-sre/{template}/path/{template}-1",
            ["app-sre/test/path/test-1", "app-sre/test/path/test-2"],
            ["app-sre/test/path/test-1"],
        ),
        (
            "app-sre/{template}/path/test-1",
            ["app-sre/test/path/test-1", "app-sre/test/path/test-2"],
            ["app-sre/test/path/test-1"],
        ),
        (
            "app-sre/test/pa{th}/test-1",
            ["app-sre/test/path/test-1", "app-sre/test/path/test-2"],
            ["app-sre/test/path/test-1"],
        ),
    ],
)
def test_get_secrets_from_templated_path(path, vault_list, return_value):
    assert integ.get_secrets_from_templated_path(path, vault_list) == return_value


def test_get_jenkins_secret_list_templating(mocker):
    mock_vault_client = mocker.patch(
        "reconcile.utils.vault._VaultClient", autospec=True
    )
    mock_vault_client.list_all.side_effect = [
        ["path/test-1/secret", "path/test-2/secret"]
    ]

    test = fxt.get_anymarkup("jenkins_configs/jenkins_config_insta_path.yaml")
    assert integ.get_jenkins_secret_list(
        mock_vault_client, "jenkins-instance", JenkinsConfigsQueryData(**test)
    ) == ["path/test-1/secret", "path/test-2/secret"]


def test_get_policy_paths_real_data():
    test = fxt.get_anymarkup("vault_policies/vault_policies_query_data.yaml")
    assert integ.get_policy_paths(
        "vault-test-policy",
        "vault-instance",
        vault_policies.VaultPoliciesQueryData(**test),
    ) == ["path/test-1/*", "path/test-2/*"]


@pytest.mark.parametrize(
    "dry_run, secret_version, path", [[False, 1, "path"], [True, 1, "path"]]
)
def test_write_dummy_version(dry_run, secret_version, path, mocker):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    integ.write_dummy_versions(
        dry_run=dry_run,
        dest_vault=vault_client,
        secret_version=secret_version,
        path=path,
    )
    if not dry_run:
        vault_client.write.assert_called_once_with(
            {"path": path, "data": {"dummy": "data"}}, False, True
        )
    else:
        vault_client.write.assert_not_called()


@pytest.mark.parametrize(
    "dry_run, current_dest_version, current_source_version, path",
    [[False, 1, 2, "path"], [True, 1, 2, "path"]],
)
def test_deep_copy_versions(
    dry_run, current_dest_version, current_source_version, path, mocker
):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.return_value = [{"test": "data"}, 2]

    integ.deep_copy_versions(
        dry_run=dry_run,
        source_vault=vault_client,
        dest_vault=vault_client,
        current_dest_version=current_dest_version,
        current_source_version=current_source_version,
        path=path,
    )

    secret_dict = {"path": path, "version": 2}
    if dry_run:
        vault_client.read_all_with_version.assert_called_once_with(secret_dict)
        vault_client.write.assert_not_called()
    else:
        write_dict = {"path": path, "data": {"test": "data"}}
        vault_client.read_all_with_version.assert_called_once_with(secret_dict)
        vault_client.write.assert_called_once_with(write_dict, False, True)


@pytest.mark.parametrize(
    "dry_run, current_dest_version, current_source_version, path",
    [[False, 1, 2, "path"], [True, 1, 2, "path"]],
)
def test_deep_copy_versions_exception(
    dry_run, current_dest_version, current_source_version, path, mocker
):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)
    write_dummy_versions = mocker.patch(
        "reconcile.vault_replication.write_dummy_versions", autospec=True
    )

    vault_client.read_all_with_version.side_effect = SecretVersionNotFound()

    integ.deep_copy_versions(
        dry_run=dry_run,
        source_vault=vault_client,
        dest_vault=vault_client,
        current_dest_version=current_dest_version,
        current_source_version=current_source_version,
        path=path,
    )

    secret_dict = {"path": path, "version": 2}
    if dry_run:
        vault_client.read_all_with_version.assert_called_once_with(secret_dict)
        write_dummy_versions.assert_called()
        vault_client.write.assert_not_called()
    else:
        vault_client.read_all_with_version.assert_called_once_with(secret_dict)
        write_dummy_versions.assert_called()


def test_copy_vault_secret_forbidden_access(mocker):
    dry_run = True
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)
    vault_client.read_all_with_version.side_effect = SecretAccessForbidden()

    with pytest.raises(SecretAccessForbidden):
        integ.copy_vault_secret(
            dry_run=dry_run,
            source_vault=vault_client,
            dest_vault=vault_client,
            path="path",
        )


def test_copy_vault_secret_not_found_v2(mocker):
    dry_run = True
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = [["secret", 2], SecretNotFound()]
    deep_copy_versions = mocker.patch(
        "reconcile.vault_replication.deep_copy_versions", autospec=True
    )

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    vault_client.read_all_with_version.assert_called()
    deep_copy_versions.assert_called()


@pytest.mark.parametrize("dry_run, path", [[False, "path"], [True, "path"]])
def test_copy_vault_secret_not_found_v1(dry_run, path, mocker):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = [
        ["secret", None],
        SecretNotFound(),
        ["secret", None],
    ]
    deep_copy_versions = mocker.patch(
        "reconcile.vault_replication.deep_copy_versions", autospec=True
    )

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    if not dry_run:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_called_once_with(
            {"path": path, "data": "secret"}, False, True
        )
        deep_copy_versions.assert_not_called()
    else:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_not_called()
        deep_copy_versions.assert_not_called()


def test_copy_vault_secret_found_v2(mocker):
    dry_run = True
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = [["secret", 2], ["secret", 1]]
    deep_copy_versions = mocker.patch(
        "reconcile.vault_replication.deep_copy_versions", autospec=True
    )

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    vault_client.read_all_with_version.assert_called()
    deep_copy_versions.assert_called_once_with(
        dry_run, vault_client, vault_client, 1, 2, "path"
    )


def test_copy_vault_secret_found_same_version_v2(mocker):
    dry_run = True
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = [["secret", 2], ["secret", 2]]
    deep_copy_versions = mocker.patch(
        "reconcile.vault_replication.deep_copy_versions", autospec=True
    )

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    vault_client.read_all_with_version.assert_called()
    deep_copy_versions.assert_not_called()


@pytest.mark.parametrize(
    "dry_run, path, return_values",
    [
        [False, "path", [["secret2", None], ["secret", None], ["secret", None]]],
        [True, "path", [["secret2", None], ["secret", None], ["secret", None]]],
    ],
)
def test_copy_vault_secret_found_v1(dry_run, path, return_values, mocker):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = return_values
    deep_copy_versions = mocker.patch(
        "reconcile.vault_replication.deep_copy_versions", autospec=True
    )

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    if not dry_run:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_called_once_with(
            {"path": path, "data": "secret"}, False, True
        )
        deep_copy_versions.assert_not_called()
    else:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_not_called()


@pytest.mark.parametrize(
    "dry_run, path, return_values",
    [
        [False, "path", [["secret", None], ["secret", None], ["secret", None]]],
        [True, "path", [["secret", None], ["secret", None], ["secret", None]]],
    ],
)
def test_copy_vault_secret_found_v1_same_value(dry_run, path, return_values, mocker):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)

    vault_client.read_all_with_version.side_effect = return_values

    integ.copy_vault_secret(
        dry_run=dry_run, source_vault=vault_client, dest_vault=vault_client, path="path"
    )
    if not dry_run:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_not_called()
    else:
        vault_client.read_all_with_version.assert_called()
        vault_client.write.assert_not_called()


def test_get_policy_secret_list(mocker):
    vault_client = mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)
    vault_client.list_all.side_effect = [
        ["policy/path/1/secret1", "policy/path/1/secret2"],
        ["policy/path/2/secret1", "policy/path/2/secret2"],
    ]

    assert integ.get_policy_secret_list(
        vault_client, ["policy/path/1/*", "policy/path/2/*"]
    ) == [
        "policy/path/1/secret1",
        "policy/path/1/secret2",
        "policy/path/2/secret1",
        "policy/path/2/secret2",
    ]
