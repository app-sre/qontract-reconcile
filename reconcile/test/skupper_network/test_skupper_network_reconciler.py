import copy
from typing import Any
from unittest.mock import (
    ANY,
    call,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.skupper_network import reconciler
from reconcile.skupper_network.models import SkupperSite
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap


@pytest.mark.parametrize("dry_run", [True, False])
def test_skupper_network_reconciler_delete_skupper_resources(
    dry_run: bool,
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
    fake_site_configmap: dict[str, Any],
) -> None:
    another_fake_configmap = copy.deepcopy(fake_site_configmap)
    another_fake_configmap["metadata"]["name"] = "another-fake-configmap"
    site = skupper_sites[0]
    oc.get_items.side_effect = [
        # by-label
        (another_fake_configmap,),
        # by-name
        (fake_site_configmap,),
    ]
    reconciler.delete_skupper_site(
        site,
        oc_map,
        dry_run=dry_run,
        integration_managed_kinds=["ConfigMap"],
        labels={},
    )
    if dry_run:
        assert oc.delete.call_count == 0
    else:
        assert oc.delete.call_count == 2
        oc.delete.assert_has_calls(
            [
                call(
                    site.namespace.name,
                    "ConfigMap",
                    another_fake_configmap["metadata"]["name"],
                ),
                call(
                    site.namespace.name,
                    "ConfigMap",
                    fake_site_configmap["metadata"]["name"],
                ),
            ]
        )


def test_skupper_network_reconciler_get_token(
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
    fake_site_configmap: dict[str, Any],
) -> None:
    oc.get.return_value = fake_site_configmap
    reconciler._get_token(
        oc_map, skupper_sites[0], name=fake_site_configmap["metadata"]["name"]
    ) == fake_site_configmap


@pytest.mark.parametrize("dry_run", [True, False])
def test_skupper_network_reconciler_create_token(
    dry_run: bool,
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
) -> None:
    site = skupper_sites[0]
    connected_site = skupper_sites[1]

    reconciler._create_token(
        oc_map,
        site,
        connected_site,
        dry_run=dry_run,
        integration="fake-integration",
        integration_version="fake-version",
        labels={},
    )

    if dry_run:
        assert oc.apply.call_count == 0
    else:
        assert oc.apply.call_count == 1
        oc.apply.assert_called_with(connected_site.namespace.name, ANY)


@pytest.fixture
def fake_token() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": "name",
            "labels": {"skupper.io/type": "connection-token"},
        },
        "data": {
            "fake-key": "fake-value",
        },
    }


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("is_usable_connection_token", [True, False])
def test_skupper_network_reconciler_transfer_token(
    dry_run: bool,
    is_usable_connection_token: bool,
    mocker: MockerFixture,
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
    fake_token: dict[str, Any],
) -> None:
    mocker.patch(
        "reconcile.skupper_network.site_controller.SiteController.is_usable_connection_token",
        return_value=is_usable_connection_token,
    )
    site = skupper_sites[0]
    connected_site = skupper_sites[1]

    reconciler._transfer_token(
        oc_map,
        site,
        connected_site,
        dry_run=dry_run,
        integration="fake-integration",
        integration_version="fake-version",
        token=fake_token,
    )

    if dry_run or not is_usable_connection_token:
        assert oc.apply.call_count == 0
    else:
        assert oc.apply.call_count == 1
        oc.delete.assert_called_with(connected_site.namespace.name, "Secret", ANY)
        oc.apply.assert_called_with(site.namespace.name, ANY)


@pytest.mark.parametrize(
    "local_site_exists",
    [True, False],
)
@pytest.mark.parametrize(
    "remote_site_exists",
    [True, False],
)
@pytest.mark.parametrize(
    "local_token",
    [
        {},
        {"data": {"fake-key": "fake-value"}},
    ],
)
@pytest.mark.parametrize(
    "remote_token",
    [
        {},
        {"data": {"fake-key": "fake-value"}},
    ],
)
def test_skupper_network_reconciler_connect_sites(
    local_site_exists: bool,
    remote_site_exists: bool,
    local_token: dict[str, Any],
    remote_token: dict[str, Any],
    mocker: MockerFixture,
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
) -> None:
    oc.project_exists.side_effect = [local_site_exists, remote_site_exists]  # type: ignore

    transfer_token = mocker.patch(
        "reconcile.skupper_network.reconciler._transfer_token",
    )
    create_token = mocker.patch(
        "reconcile.skupper_network.reconciler._create_token",
    )
    get_token = mocker.patch(
        "reconcile.skupper_network.reconciler._get_token",
        side_effect=[local_token, remote_token],
    )
    site = skupper_sites[0]
    site.connected_sites = {skupper_sites[1]}
    dry_run = True
    reconciler.connect_sites(
        site,
        oc_map,
        dry_run=dry_run,
        integration="fake-integration",
        integration_version="fake-version",
        labels={},
    )
    if not local_site_exists:
        assert transfer_token.call_count == 0
        assert create_token.call_count == 0
        assert get_token.call_count == 0
    elif local_token:
        assert transfer_token.call_count == 0
        assert create_token.call_count == 0
        assert get_token.call_count == 1
    elif not local_token and not remote_site_exists:
        assert transfer_token.call_count == 0
        assert create_token.call_count == 0
        assert get_token.call_count == 1
    elif not local_token and remote_site_exists and not remote_token:
        assert transfer_token.call_count == 0
        assert get_token.call_count == 2
        create_token.assert_called_with(
            oc_map, site, skupper_sites[1], dry_run, "fake-integration", "fake-version"
        )
    elif not local_token and remote_site_exists and remote_token:
        assert create_token.call_count == 0
        assert get_token.call_count == 2
        transfer_token.assert_called_with(
            oc_map,
            site,
            skupper_sites[1],
            dry_run,
            "fake-integration",
            "fake-version",
            remote_token,
        )


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "token_secrets, expected_deletion_count",
    [
        ([], 0),
        ([{"kind": "Secret", "metadata": {"name": "unused-token"}}], 1),
        (
            [
                {"kind": "Secret", "metadata": {"name": "unused-token"}},
                {"kind": "Secret", "metadata": {"name": "another-unused-token"}},
            ],
            2,
        ),
        (
            [
                {"kind": "Secret", "metadata": {"name": "unused-token"}},
                {"kind": "Secret", "metadata": {"name": "another-unused-token"}},
                {
                    "kind": "Secret",
                    "metadata": {"name": "advanced-private-1-private-1"},
                },
            ],
            2,
        ),
    ],
)
def test_skupper_network_reconciler_delete_unused_tokens(
    dry_run: bool,
    token_secrets: list[dict[str, Any]],
    expected_deletion_count: int,
    oc_map: OCMap,
    oc: OCNative,
    skupper_sites: list[SkupperSite],
) -> None:
    edge_1 = skupper_sites[0]
    private_1 = skupper_sites[2]
    edge_1.connected_sites = {private_1}
    oc.get_items.return_value = token_secrets
    reconciler.delete_unused_tokens(
        edge_1,
        oc_map,
        dry_run=dry_run,
    )
    if dry_run:
        assert oc.delete.call_count == 0
    elif not token_secrets:
        assert oc.delete.call_count == 0
    else:
        assert oc.delete.call_count == expected_deletion_count
