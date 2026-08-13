from __future__ import annotations

import base64
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Any
from urllib.error import URLError

import pytest

import reconcile.openshift_cluster_bots as ocb
from reconcile.gql_definitions.openshift_cluster_bots.clusters import (
    AutomationTokenEntryV1,
    ClusterV1,
    VaultSecret,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


def vault_secret_dict(path: str, field: str) -> dict[str, str | None]:
    return VaultSecret(path=path, field=field, version=None, format=None).model_dump(
        by_alias=True
    )


def automation_token_entry(
    name: str = "sa-token",
    namespace: str = "dedicated-admin",
    active: bool | None = None,
    delete: bool | None = None,
    secret: dict | None = None,
) -> dict:
    return {
        "name": name,
        "namespace": namespace,
        "active": active,
        "delete": delete,
        "secret": secret,
    }


@pytest.fixture
def secret() -> dict[str, str | None]:
    return vault_secret_dict(path="app-sre/bot", field="token")


@pytest.fixture
def admin_secret() -> dict[str, str | None]:
    return vault_secret_dict(path="app-sre/admin-bot", field="token")


@pytest.fixture
def cluster(
    gql_class_factory: Callable[..., ClusterV1],
) -> Callable[..., ClusterV1]:
    def builder(
        server_url: str = "",
        secret: dict | None = None,
        admin: bool | None = None,
        admin_secret: dict | None = None,
        ocm: bool = True,
        automation_tokens: list[dict] | None = None,
        cluster_admin_automation_tokens: list[dict] | None = None,
    ) -> ClusterV1:
        ocm_data = {
            "name": "ocm-production",
            "environment": {
                "name": "ocm-production",
                "url": "https://api.openshift.com",
                "accessTokenClientId": "ocm-client-id",
                "accessTokenUrl": "https://sso.com/openid/token",
                "accessTokenClientSecret": vault_secret_dict(
                    path="ocm/creds", field="client_secret"
                ),
            },
            "orgId": "ocm-org-id",
            "accessTokenClientId": "ocm-client-id",
            "accessTokenUrl": "https://sso.com/openid/token",
            "accessTokenClientSecret": vault_secret_dict(
                path="ocm/creds", field="client_secret"
            ),
        }
        return gql_class_factory(
            ClusterV1,
            {
                "name": "cluster",
                "serverUrl": server_url,
                "ocm": ocm_data if ocm else None,
                "automationToken": secret,
                "automationTokens": automation_tokens,
                "clusterAdmin": admin,
                "clusterAdminAutomationToken": admin_secret,
                "clusterAdminAutomationTokens": cluster_admin_automation_tokens,
                "disable": None,
            },
        )

    return builder


@pytest.fixture
def integ_params() -> dict[str, Any]:
    return {
        "gitlab_project_id": "000",
        "vault_creds_path": "/vault/path",
        "dedicated_admin_ns": "dedicated-admin-ns",
        "dedicated_admin_sa": "dedicated-admin-sa",
        "cluster_admin_ns": "cluster-admin-ns",
        "cluster_admin_sa": "cluster-admin-sa",
        "dry_run": False,
    }


@pytest.fixture
def config(integ_params: dict[str, Any]) -> ocb.Config:
    params = dict(integ_params)
    params.pop("dry_run")
    return ocb.Config(**params, dry_run=False)


def test_cluster_misses_bot_tokens(
    cluster: Callable, secret: VaultSecret, admin_secret: VaultSecret
) -> None:
    # singular token logic (legacy)
    assert ocb.cluster_misses_bot_tokens(cluster())
    assert not ocb.cluster_misses_bot_tokens(cluster(secret=secret))
    assert ocb.cluster_misses_bot_tokens(cluster(secret=secret, admin=True))
    assert not ocb.cluster_misses_bot_tokens(
        cluster(secret=secret, admin=True, admin_secret=admin_secret)
    )


def test_cluster_misses_bot_tokens_list_based(
    cluster: Callable, secret: VaultSecret, admin_secret: VaultSecret
) -> None:
    active_entry = automation_token_entry(
        active=True, secret=vault_secret_dict("p", "token")
    )
    inactive_entry = automation_token_entry(
        active=False, secret=vault_secret_dict("p", "token")
    )
    delete_entry = automation_token_entry(
        active=True, delete=True, secret=vault_secret_dict("p", "token")
    )
    no_secret_entry = automation_token_entry(active=True)

    # list token satisfies the da requirement
    assert not ocb.cluster_misses_bot_tokens(cluster(automation_tokens=[active_entry]))
    # inactive / delete / no-secret entries don't count
    assert ocb.cluster_misses_bot_tokens(cluster(automation_tokens=[inactive_entry]))
    assert ocb.cluster_misses_bot_tokens(cluster(automation_tokens=[delete_entry]))
    assert ocb.cluster_misses_bot_tokens(cluster(automation_tokens=[no_secret_entry]))
    # list token for da, but missing cluster-admin token
    assert ocb.cluster_misses_bot_tokens(
        cluster(automation_tokens=[active_entry], admin=True)
    )
    # list token satisfies both da and cluster-admin requirements
    assert not ocb.cluster_misses_bot_tokens(
        cluster(
            automation_tokens=[active_entry],
            admin=True,
            cluster_admin_automation_tokens=[active_entry],
        )
    )
    # singular da + list cluster-admin also works
    assert not ocb.cluster_misses_bot_tokens(
        cluster(
            secret=secret, admin=True, cluster_admin_automation_tokens=[active_entry]
        )
    )


def test_cluster_is_reachable(mocker: MockerFixture, cluster: Callable) -> None:
    assert not ocb.cluster_is_reachable(cluster(server_url=""))
    urlopen_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.urllib.request.urlopen", autospec=True
    )
    c = cluster(server_url="https://my.api")
    urlopen_mock.return_value.getcode.return_value = 200
    assert ocb.cluster_is_reachable(c)

    urlopen_mock.return_value.getcode.return_value = 404
    assert not ocb.cluster_is_reachable(c)

    urlopen_mock.return_value = None
    assert not ocb.cluster_is_reachable(c)

    urlopen_mock.side_effect = URLError(reason="something")
    assert not ocb.cluster_is_reachable(c)


def test_oc(mocker: MockerFixture) -> None:
    run_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.subprocess.run", autospec=True
    )
    ret_mock = run_mock.return_value

    args: list = ["kc", "ns", ["cmd", "attr"]]
    run_args: list = [
        "oc",
        "--kubeconfig",
        "kc",
        "-n",
        "ns",
        "-o",
        "json",
        "cmd",
        "attr",
    ]
    run_kwargs = {"input": None, "check": True, "capture_output": True}
    ret_mock.stdout = None
    assert ocb.oc(*args) is None
    run_mock.assert_called_once_with(run_args, **run_kwargs)

    ret_mock.stdout = b"{}"
    assert ocb.oc(*args) == {}

    ret_mock.stdout = b""
    assert ocb.oc(*args) is None

    run_mock.side_effect = CalledProcessError(returncode=4, cmd="oc")
    with pytest.raises(CalledProcessError):
        ocb.oc(*args)


def test_retrieve_token(mocker: MockerFixture) -> None:
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    # avoid waiting during retries
    mocker.patch("sretoolbox.utils.retry.time.sleep")

    oc_mock.return_value = {}
    with pytest.raises(ocb.TokenNotReadyError):
        ocb.retrieve_token("kc", "ns", "sa")
    assert oc_mock.call_count == 3

    oc_mock.return_value = {"data": {"token": base64.b64encode(b"Got It!")}}
    assert ocb.retrieve_token("kc", "ns", "sa") == "Got It!"


def test_vault_secret_for_entry(config: ocb.Config) -> None:
    entry = AutomationTokenEntryV1(
        name="tok", namespace="ns", active=None, delete=None, secret=None
    )
    assert ocb.vault_secret_for_entry("mycluster", config, entry) == {
        "path": "/vault/path/mycluster/ns/tok",
        "field": "token",
    }


def test_get_sa_name(config: ocb.Config) -> None:
    assert ocb.get_sa_name(config, cluster_admin=False) == "dedicated-admin-sa"
    assert ocb.get_sa_name(config, cluster_admin=True) == "cluster-admin-sa"


def test_cluster_needs_list_processing(cluster: Callable, secret: dict) -> None:
    assert not ocb.cluster_needs_list_processing(cluster())
    assert ocb.cluster_needs_list_processing(
        cluster(automation_tokens=[automation_token_entry(secret=None)])
    )
    assert not ocb.cluster_needs_list_processing(
        cluster(automation_tokens=[automation_token_entry(secret=secret)])
    )
    assert ocb.cluster_needs_list_processing(
        cluster(automation_tokens=[automation_token_entry(secret=secret, delete=True)])
    )
    assert ocb.cluster_needs_list_processing(
        cluster(cluster_admin_automation_tokens=[automation_token_entry(secret=None)])
    )


def test_filter_clusters_legacy_vs_list(
    mocker: MockerFixture, cluster: Callable, secret: dict
) -> None:
    mocker.patch(
        "reconcile.openshift_cluster_bots.cluster_is_reachable", return_value=True
    )

    legacy_needs_work = cluster()
    legacy_synced = cluster(secret=secret)
    list_needs_work = cluster(automation_tokens=[automation_token_entry(secret=None)])
    list_synced = cluster(automation_tokens=[automation_token_entry(secret=secret)])

    legacy_result, list_result = ocb.filter_clusters([
        legacy_needs_work,
        legacy_synced,
        list_needs_work,
        list_synced,
    ])

    assert legacy_result == [legacy_needs_work]
    assert list_result == [list_needs_work]


def test_process_entry_create_new(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable
) -> None:
    c = cluster(automation_tokens=[automation_token_entry(name="tok", namespace="ns")])
    entry = c.automation_tokens[0]

    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.side_effect = [
        CalledProcessError(returncode=1, cmd="oc", stderr=b'Error from server (NotFound): secrets "tok" not found'),  # oc_get_secret: not found
        {},  # apply ServiceAccount
        {},  # apply Secret
        {"data": {"token": base64.b64encode(b"mytoken")}},  # retrieve_token
        {},  # oc_annotate_secret
    ]
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )
    mocker.patch("sretoolbox.utils.retry.time.sleep")

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "created"
    assert result.vault_secret == {
        "path": "/vault/path/cluster/ns/tok",
        "field": "token",
    }
    assert oc_mock.call_count == 5
    vault_mock.return_value.write.assert_called_once_with(
        {
            "path": "/vault/path/cluster/ns/tok",
            "data": {
                "server": "",
                "token": "mytoken",
                "username": "ns/dedicated-admin-sa # not used by automation",
            },
        },
        decode_base64=False,
    )


def test_process_entry_existing_unsynced(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable
) -> None:
    c = cluster(automation_tokens=[automation_token_entry(name="tok", namespace="ns")])
    entry = c.automation_tokens[0]

    existing_secret = {
        "metadata": {
            "labels": {ocb.MANAGED_LABEL_KEY: "dedicated-admin-sa"},
            "annotations": {},
        },
        "data": {"token": base64.b64encode(b"existingtoken")},
    }
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.side_effect = [existing_secret, {}]
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "synced"
    assert result.vault_secret == {
        "path": "/vault/path/cluster/ns/tok",
        "field": "token",
    }
    assert oc_mock.call_count == 2
    vault_mock.return_value.write.assert_called_once()


def test_process_entry_already_synced(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable, secret: dict
) -> None:
    c = cluster(
        automation_tokens=[
            automation_token_entry(name="tok", namespace="ns", secret=secret)
        ]
    )
    entry = c.automation_tokens[0]

    existing_secret = {
        "metadata": {
            "labels": {ocb.MANAGED_LABEL_KEY: "dedicated-admin-sa"},
            "annotations": {ocb.VAULT_PATH_ANNOTATION_KEY: "app-sre/bot"},
        },
        "data": {"token": base64.b64encode(b"tok")},
    }
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.return_value = existing_secret
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "skipped"
    assert result.vault_secret is None
    assert oc_mock.call_count == 1
    vault_mock.return_value.write.assert_not_called()


def test_process_entry_unmanaged(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable
) -> None:
    c = cluster(automation_tokens=[automation_token_entry(name="tok", namespace="ns")])
    entry = c.automation_tokens[0]

    existing_secret: dict[str, Any] = {
        "metadata": {"labels": {}, "annotations": {}},
        "data": {},
    }
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.return_value = existing_secret
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "skipped"
    assert result.vault_secret is None
    vault_mock.return_value.write.assert_not_called()


def test_process_entry_delete(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable, secret: dict
) -> None:
    c = cluster(
        automation_tokens=[
            automation_token_entry(
                name="tok", namespace="ns", delete=True, secret=secret
            )
        ]
    )
    entry = c.automation_tokens[0]

    existing_secret = {
        "metadata": {
            "labels": {ocb.MANAGED_LABEL_KEY: "dedicated-admin-sa"},
            "annotations": {},
        },
    }
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.side_effect = [existing_secret, {}]
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "deleted"
    assert oc_mock.call_count == 2
    vault_mock.return_value.delete.assert_called_once_with("app-sre/bot")


def test_process_entry_delete_unmanaged(
    mocker: MockerFixture, config: ocb.Config, cluster: Callable, secret: dict
) -> None:
    c = cluster(
        automation_tokens=[
            automation_token_entry(
                name="tok", namespace="ns", delete=True, secret=secret
            )
        ]
    )
    entry = c.automation_tokens[0]

    existing_secret: dict[str, Any] = {"metadata": {"labels": {}, "annotations": {}}}
    oc_mock = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    oc_mock.return_value = existing_secret
    vault_mock = mocker.patch(
        "reconcile.openshift_cluster_bots.VaultClient.get_instance"
    )

    result = ocb.process_entry("kubeconfig", c, config, entry, cluster_admin=False)

    assert result.action == "skipped"
    assert oc_mock.call_count == 1
    vault_mock.return_value.delete.assert_not_called()


class Mocks:  # ruff: ignore[class-as-data-structure]
    def __init__(
        self,
        oc: MagicMock,
        vault: MagicMock,
        submit_mr: MagicMock,
        submit_list_mr: MagicMock,
    ) -> None:
        self.oc = oc
        self.vault = vault
        self.submit_mr = submit_mr
        self.submit_list_mr = submit_list_mr


def _setup_mocks(
    mocker: MockerFixture,
    legacy_clusters: list[ClusterV1] | None = None,
    list_clusters: list[ClusterV1] | None = None,
) -> Mocks:
    mocker.patch("reconcile.openshift_cluster_bots.gql")
    mocker.patch("reconcile.openshift_cluster_bots.clusters_gql")
    filter_clusters = mocker.patch(
        "reconcile.openshift_cluster_bots.filter_clusters", autospec=True
    )
    filter_clusters.return_value = (legacy_clusters or [], list_clusters or [])
    # avoid waiting during retries
    mocker.patch("sretoolbox.utils.retry.time.sleep")
    ocm_map = mocker.patch("reconcile.openshift_cluster_bots.OCMMap", autospec=True)
    get_ocm_map = mocker.patch(
        "reconcile.openshift_cluster_bots.get_ocm_map", autospec=True
    )
    get_ocm_map.return_value = ocm_map
    mocker.patch("reconcile.openshift_cluster_bots.tempfile", autospec=True)
    oc = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    vault = mocker.patch("reconcile.openshift_cluster_bots.VaultClient.get_instance")
    submit_mr = mocker.patch(
        "reconcile.openshift_cluster_bots.submit_mr", autospec=True
    )
    submit_list_mr = mocker.patch(
        "reconcile.openshift_cluster_bots.submit_list_mr", autospec=True
    )
    return Mocks(oc, vault, submit_mr, submit_list_mr)


def test_run_nothing_to_do(mocker: MockerFixture, integ_params: dict[str, Any]) -> None:
    _setup_mocks(mocker)
    with pytest.raises(SystemExit):
        ocb.run(**integ_params)


def test_run_dry_run(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    integ_params["dry_run"] = True
    mocks = _setup_mocks(mocker, legacy_clusters=[cluster(server_url="https://api")])
    ocb.run(**integ_params)
    mocks.oc.assert_not_called()
    mocks.vault.assert_not_called()
    mocks.submit_mr.assert_not_called()
    mocks.submit_list_mr.assert_not_called()


def test_run_no_cluster_admin(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    mocks = _setup_mocks(mocker, legacy_clusters=[cluster(server_url="https://api")])
    mocks.oc.return_value = {"data": {"token": base64.b64encode(b"mytoken")}}
    ocb.run(**integ_params)
    assert mocks.oc.call_count == 3
    mocks.vault.assert_called_once()
    mocks.submit_mr.assert_called_once()
    mocks.submit_list_mr.assert_not_called()


def test_run_cluster_admin(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    mocks = _setup_mocks(
        mocker, legacy_clusters=[cluster(server_url="https://api", admin=True)]
    )
    mocks.oc.return_value = {"data": {"token": base64.b64encode(b"mytoken")}}
    ocb.run(**integ_params)
    assert mocks.oc.call_count == 8
    mocks.vault.assert_called_once()
    mocks.submit_mr.assert_called_once()
    mocks.submit_list_mr.assert_not_called()


def test_run_list_based(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    c = cluster(automation_tokens=[automation_token_entry(name="tok", namespace="ns")])
    mocks = _setup_mocks(mocker, list_clusters=[c])
    mocks.oc.return_value = {"metadata": {"labels": {}, "annotations": {}}, "data": {}}
    ocb.run(**integ_params)
    mocks.submit_mr.assert_not_called()
    mocks.submit_list_mr.assert_called_once()


def test_run_mixed(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    legacy_cluster = cluster(server_url="https://api")
    list_cluster = cluster(
        automation_tokens=[automation_token_entry(name="tok", namespace="ns")]
    )
    mocks = _setup_mocks(
        mocker, legacy_clusters=[legacy_cluster], list_clusters=[list_cluster]
    )
    mocks.oc.return_value = {"data": {"token": base64.b64encode(b"mytoken")}}
    ocb.run(**integ_params)
    mocks.submit_mr.assert_called_once()
    mocks.submit_list_mr.assert_called_once()


def test_run_list_dry_run(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    integ_params["dry_run"] = True
    c = cluster(automation_tokens=[automation_token_entry(name="tok", namespace="ns")])
    mocks = _setup_mocks(mocker, list_clusters=[c])
    mocks.oc.return_value = None
    ocb.run(**integ_params)
    mocks.oc.assert_called_once()
    mocks.vault.assert_not_called()
    mocks.submit_mr.assert_not_called()
    mocks.submit_list_mr.assert_not_called()
