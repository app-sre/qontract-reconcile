import base64
from collections.abc import Callable
from subprocess import CalledProcessError
from typing import Any
from unittest.mock import MagicMock
from urllib.error import URLError

import pytest
from pytest_mock import MockerFixture

import reconcile.openshift_cluster_bots as ocb
from reconcile.gql_definitions.openshift_cluster_bots.clusters import (
    ClusterV1,
    VaultSecret,
)


def vault_secret(path: str, field: str) -> VaultSecret:
    return VaultSecret(path=path, field=field, version=None, format=None)


def vault_secret_dict(path: str, field: str) -> dict[str, str | None]:
    return vault_secret(path=path, field=field).dict(by_alias=True)


@pytest.fixture
def secret() -> VaultSecret:
    return vault_secret(path="app-sre/bot", field="token")


@pytest.fixture
def admin_secret() -> VaultSecret:
    return vault_secret(path="app-sre/admin-bot", field="token")


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
                "clusterAdmin": admin,
                "clusterAdminAutomationToken": admin_secret,
                "disable": None,
            },
        )

    return builder


def test_cluster_misses_bot_tokens(
    cluster: Callable, secret: VaultSecret, admin_secret: VaultSecret
) -> None:
    assert ocb.cluster_misses_bot_tokens(cluster())
    assert not ocb.cluster_misses_bot_tokens(cluster(secret=secret))
    assert ocb.cluster_misses_bot_tokens(cluster(secret=secret, admin=True))
    assert not ocb.cluster_misses_bot_tokens(
        cluster(secret=secret, admin=True, admin_secret=admin_secret)
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
    with pytest.raises(ocb.TokenNotReadyException):
        ocb.retrieve_token("kc", "ns", "sa")
    assert oc_mock.call_count == 3

    oc_mock.return_value = {"data": {"token": base64.b64encode(b"Got It!")}}
    assert ocb.retrieve_token("kc", "ns", "sa") == "Got It!"


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


class Mocks:
    def __init__(self, oc: MagicMock, vault: MagicMock, submit_mr: MagicMock) -> None:
        self.oc = oc
        self.vault = vault
        self.submit_mr = submit_mr


def _setup_mocks(mocker: MockerFixture, filtered_clusters: list[ClusterV1]) -> Mocks:
    mocker.patch("reconcile.openshift_cluster_bots.gql")
    mocker.patch("reconcile.openshift_cluster_bots.clusters_gql")
    filter_clusters = mocker.patch(
        "reconcile.openshift_cluster_bots.filter_clusters", autospec=True
    )
    filter_clusters.return_value = filtered_clusters
    # avoid waiting during retries
    mocker.patch("sretoolbox.utils.retry.time.sleep")
    ocm_map = mocker.patch("reconcile.openshift_cluster_bots.OCMMap", autospec=True)
    get_ocm_map = mocker.patch(
        "reconcile.openshift_cluster_bots.get_ocm_map", autospec=True
    )
    get_ocm_map.return_value = ocm_map
    mocker.patch("reconcile.openshift_cluster_bots.tempfile", autospec=True)
    oc = mocker.patch("reconcile.openshift_cluster_bots.oc", autospec=True)
    vault = mocker.patch("reconcile.openshift_cluster_bots.VaultClient")
    submit_mr = mocker.patch(
        "reconcile.openshift_cluster_bots.submit_mr", autospec=True
    )
    return Mocks(oc, vault, submit_mr)


def test_run_nothing_to_do(mocker: MockerFixture, integ_params: dict[str, Any]) -> None:
    _setup_mocks(mocker, filtered_clusters=[])
    with pytest.raises(SystemExit):
        ocb.run(**integ_params)


def test_run_dry_run(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    integ_params["dry_run"] = True
    mocks = _setup_mocks(mocker, filtered_clusters=[cluster(server_url="https://api")])
    ocb.run(**integ_params)
    mocks.oc.assert_not_called()
    mocks.vault.assert_not_called()
    mocks.submit_mr.assert_not_called()


def test_run_no_cluster_admin(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    mocks = _setup_mocks(mocker, filtered_clusters=[cluster(server_url="https://api")])
    mocks.oc.return_value = {"data": {"token": base64.b64encode(b"mytoken")}}
    ocb.run(**integ_params)
    assert mocks.oc.call_count == 3
    mocks.vault.assert_called_once()
    mocks.submit_mr.assert_called_once()


def test_run_cluster_admin(
    mocker: MockerFixture, integ_params: dict[str, Any], cluster: Callable
) -> None:
    mocks = _setup_mocks(
        mocker, filtered_clusters=[cluster(server_url="https://api", admin=True)]
    )
    mocks.oc.return_value = {"data": {"token": base64.b64encode(b"mytoken")}}
    ocb.run(**integ_params)
    assert mocks.oc.call_count == 8
    mocks.vault.assert_called_once()
    mocks.submit_mr.assert_called_once()
