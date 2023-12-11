from collections.abc import Iterable
from typing import Optional
from unittest.mock import (
    Mock,
    call,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.rhidp import common
from reconcile.rhidp.common import (
    AUTH_NAME_LABEL_KEY,
    ISSUER_LABEL_KEY,
    STATUS_LABEL_KEY,
    Cluster,
    ClusterAuth,
    StatusValue,
    expose_base_metrics,
)
from reconcile.rhidp.metrics import RhIdpClusterCounter
from reconcile.test.ocm.fixtures import (
    build_cluster_details,
    build_label,
)
from reconcile.utils.metrics import MetricsContainer
from reconcile.utils.ocm.base import build_label_container
from reconcile.utils.ocm.labels import subscription_label_filter

VI = "vault-input-path"
ORG = "org_id"
CLN = "cluster_name"
AN = "auth_name"
IURL = "https://issuer-url.com/foo/bar"
VID = f"{CLN}-{ORG}-{AN}-issuer-url.com"
EXPECTED_SECRET = VaultSecret(path=f"{VI}/{VID}", field="", version=None, format=None)
RHIDP_LABELS_CONTAINER = build_label_container([
    build_label(common.STATUS_LABEL_KEY, "enabled"),
])
ORG_ID_1 = "org-id-1"
ORG_ID_2 = "org-id-2"
CLUSTER_DETAILS_1 = build_cluster_details(
    cluster_name="cluster-1",
    subscription_labels=RHIDP_LABELS_CONTAINER,
    org_id=ORG_ID_1,
)
CLUSTER_DETAILS_2 = build_cluster_details(
    cluster_name="cluster-2",
    subscription_labels=RHIDP_LABELS_CONTAINER,
    org_id=ORG_ID_2,
)


@pytest.fixture
def discover_clusters_by_labels_mock(mocker: MockerFixture) -> Mock:
    m = mocker.patch.object(
        common,
        "discover_clusters_by_labels",
        autospec=True,
    )
    m.return_value = [CLUSTER_DETAILS_1, CLUSTER_DETAILS_2]
    return m


def test_rhidp_common_cluster_object() -> None:
    cluster = Cluster(
        ocm_cluster=CLUSTER_DETAILS_1.ocm_cluster,
        auth=ClusterAuth(name="foobar", issuer=IURL, status=StatusValue.ENABLED.value),
        organization_id=ORG,
    )
    print(cluster.json())
    assert cluster.ocm_cluster == CLUSTER_DETAILS_1.ocm_cluster
    assert cluster.organization_id == ORG


@pytest.mark.parametrize(
    "auth, expected_name, expected_status, expected_rhidp_enabled, expected_oidc_enabled, expected_enforced",
    [
        (
            ClusterAuth(name="foobar", issuer=IURL, status=StatusValue.ENABLED.value),
            "foobar",
            StatusValue.ENABLED.value,
            True,
            True,
            False,
        ),
        (
            ClusterAuth(name="foobar", issuer=IURL, status=StatusValue.DISABLED.value),
            "foobar",
            StatusValue.DISABLED.value,
            False,
            False,
            False,
        ),
        (
            ClusterAuth(name="foobar", issuer=IURL, status=StatusValue.ENFORCED.value),
            "foobar",
            StatusValue.ENFORCED.value,
            True,
            True,
            True,
        ),
        (
            ClusterAuth(
                name="foobar", issuer=IURL, status=StatusValue.RHIDP_ONLY.value
            ),
            "foobar",
            StatusValue.RHIDP_ONLY.value,
            True,
            False,
            False,
        ),
        # no spaces in name
        (
            ClusterAuth(name="foo bar", issuer=IURL, status=StatusValue.ENABLED.value),
            "foo-bar",
            StatusValue.ENABLED.value,
            True,
            True,
            False,
        ),
    ],
)
def test_rhidp_common_clusterauth_object(
    auth: ClusterAuth,
    expected_name: str,
    expected_status: bool,
    expected_rhidp_enabled: bool,
    expected_oidc_enabled: bool,
    expected_enforced: bool,
) -> None:
    assert auth.name == expected_name
    assert auth.issuer == IURL
    assert auth.status == expected_status
    assert auth.rhidp_enabled == expected_rhidp_enabled
    assert auth.oidc_enabled == expected_oidc_enabled
    assert auth.enforced == expected_enforced


def test_rhidp_common_discover_clusters(discover_clusters_by_labels_mock: Mock) -> None:
    clusters = common.discover_clusters(None, None)  # type: ignore
    discover_clusters_by_labels_mock.assert_called_once_with(
        ocm_api=None,
        label_filter=subscription_label_filter().like(
            "key", f"{common.RHIDP_NAMESPACE_LABEL_KEY}%"
        ),
    )

    assert len(clusters) == 2
    assert clusters[0].ocm_cluster.name == CLUSTER_DETAILS_1.ocm_cluster.name
    assert clusters[1].ocm_cluster.name == CLUSTER_DETAILS_2.ocm_cluster.name


def test_rhidp_common_discover_clusters_with_org_filter(
    discover_clusters_by_labels_mock: Mock,
) -> None:
    clusters = common.discover_clusters(None, {ORG_ID_1})  # type: ignore
    assert len(clusters) == 1
    assert clusters[0].organization_id == ORG_ID_1


def test_rhidp_common_build_cluster_objects() -> None:
    # status enabled
    cluster_enabled = build_cluster_details(
        cluster_name="enabled",
        subscription_labels=RHIDP_LABELS_CONTAINER,
        org_id=ORG,
    )
    cluster_enabled_expected = Cluster(
        ocm_cluster=cluster_enabled.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.ENABLED.value),
        organization_id=ORG,
    )

    # status disabled
    cluster_disabled = build_cluster_details(
        cluster_name="disabled",
        subscription_labels=build_label_container([
            build_label(STATUS_LABEL_KEY, StatusValue.DISABLED.value)
        ]),
        org_id=ORG,
    )
    cluster_disabled_expected = Cluster(
        ocm_cluster=cluster_disabled.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.DISABLED.value),
        organization_id=ORG,
    )

    # status enforced
    cluster_enforced = build_cluster_details(
        cluster_name="enforced",
        subscription_labels=build_label_container([
            build_label(STATUS_LABEL_KEY, StatusValue.ENFORCED.value)
        ]),
        org_id=ORG,
    )
    cluster_enforced_expected = Cluster(
        ocm_cluster=cluster_enforced.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.ENFORCED.value),
        organization_id=ORG,
    )

    # sso-client-only
    cluster_sso_client_only = build_cluster_details(
        cluster_name="sso-client-only",
        subscription_labels=build_label_container([
            build_label(STATUS_LABEL_KEY, StatusValue.RHIDP_ONLY.value)
        ]),
        org_id=ORG,
    )
    cluster_sso_client_only_expected = Cluster(
        ocm_cluster=cluster_sso_client_only.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.RHIDP_ONLY.value),
        organization_id=ORG,
    )

    # deprecated rhidp label
    cluster_deprecated_rhidp = build_cluster_details(
        cluster_name="deprecated-rhidp",
        subscription_labels=build_label_container([
            build_label(common.RHIDP_NAMESPACE_LABEL_KEY, StatusValue.ENABLED.value)
        ]),
        org_id=ORG,
    )
    cluster_deprecated_rhidp_expected = Cluster(
        ocm_cluster=cluster_deprecated_rhidp.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.ENABLED.value),
        organization_id=ORG,
    )

    # deprecated rhidp label with disabled status
    cluster_deprecated_rhidp_disabled = build_cluster_details(
        cluster_name="deprecated-rhidp-disabled",
        subscription_labels=build_label_container([
            build_label(common.RHIDP_NAMESPACE_LABEL_KEY, StatusValue.DISABLED.value)
        ]),
        org_id=ORG,
    )
    cluster_deprecated_rhidp_disabled_expected = Cluster(
        ocm_cluster=cluster_deprecated_rhidp_disabled.ocm_cluster,
        auth=ClusterAuth(name=AN, issuer=IURL, status=StatusValue.DISABLED.value),
        organization_id=ORG,
    )

    # with auth name
    cluster_auth_name = build_cluster_details(
        cluster_name="auth-name",
        subscription_labels=build_label_container([
            build_label(STATUS_LABEL_KEY, "enabled"),
            build_label(AUTH_NAME_LABEL_KEY, "foobar-auth"),
        ]),
        org_id=ORG,
    )
    cluster_auth_name_expected = Cluster(
        ocm_cluster=cluster_auth_name.ocm_cluster,
        auth=ClusterAuth(
            name="foobar-auth", issuer=IURL, status=StatusValue.ENABLED.value
        ),
        organization_id=ORG,
    )

    # with issuer_url
    cluster_issuer_url = build_cluster_details(
        cluster_name="issuer-url",
        subscription_labels=build_label_container([
            build_label(STATUS_LABEL_KEY, "enabled"),
            build_label(ISSUER_LABEL_KEY, "https://foobar.com"),
        ]),
        org_id=ORG,
    )
    cluster_issuer_url_expected = Cluster(
        ocm_cluster=cluster_issuer_url.ocm_cluster,
        auth=ClusterAuth(
            name=AN, issuer="https://foobar.com", status=StatusValue.ENABLED.value
        ),
        organization_id=ORG,
    )
    assert common.build_cluster_objects(
        [
            cluster_enabled,
            cluster_disabled,
            cluster_enforced,
            cluster_sso_client_only,
            cluster_deprecated_rhidp,
            cluster_deprecated_rhidp_disabled,
            cluster_auth_name,
            cluster_issuer_url,
        ],
        AN,
        IURL,
    ) == [
        cluster_enabled_expected,
        cluster_disabled_expected,
        cluster_enforced_expected,
        cluster_sso_client_only_expected,
        cluster_deprecated_rhidp_expected,
        cluster_deprecated_rhidp_disabled_expected,
        cluster_auth_name_expected,
        cluster_issuer_url_expected,
    ]


@pytest.mark.parametrize(
    "vault_input_path, org_id, cluster_name, auth_name, issuer_url, vault_secret_id, expected",
    [
        # no vault secret id
        (VI, ORG, CLN, AN, IURL, None, EXPECTED_SECRET),
        # with vault secret id
        (VI, None, None, None, None, VID, EXPECTED_SECRET),
        # org_id missing
        pytest.param(
            VI,
            None,
            CLN,
            AN,
            IURL,
            None,
            EXPECTED_SECRET,
            marks=pytest.mark.xfail(strict=True, raises=ValueError),
        ),
        # cluster_name missing
        pytest.param(
            VI,
            ORG,
            None,
            AN,
            IURL,
            None,
            EXPECTED_SECRET,
            marks=pytest.mark.xfail(strict=True, raises=ValueError),
        ),
        # auth_name missing
        pytest.param(
            VI,
            ORG,
            CLN,
            None,
            IURL,
            None,
            EXPECTED_SECRET,
            marks=pytest.mark.xfail(strict=True, raises=ValueError),
        ),
        # issuer_url missing
        pytest.param(
            VI,
            ORG,
            CLN,
            AN,
            None,
            None,
            EXPECTED_SECRET,
            marks=pytest.mark.xfail(strict=True, raises=ValueError),
        ),
        # all params given - No error - vault_secret_id wins
        (VI, ORG, CLN, AN, IURL, VID, EXPECTED_SECRET),
    ],
)
def test_rhidp_common_cluster_vault_secret(
    vault_input_path: str,
    org_id: Optional[str],
    cluster_name: Optional[str],
    auth_name: Optional[str],
    issuer_url: Optional[str],
    vault_secret_id: Optional[str],
    expected: str,
) -> None:
    assert (
        common.cluster_vault_secret(
            vault_input_path=vault_input_path,
            org_id=org_id,
            cluster_name=cluster_name,
            auth_name=auth_name,
            issuer_url=issuer_url,
            vault_secret_id=vault_secret_id,
        )
        == expected
    )


def test_rhidp_common_cluster_vault_secret_id() -> None:
    assert (
        common.cluster_vault_secret_id(
            org_id="org_id",
            cluster_name="cluster_name",
            auth_name="auth_name",
            issuer_url="https://issuer-url.com:443/foo/bar",
        )
        == "cluster_name-org_id-auth_name-issuer-url.com"
    )


def test_rhidp_common_expose_base_metrics(
    mocker: MockerFixture, clusters: Iterable[Cluster]
) -> None:
    metrics_container_mock = mocker.create_autospec(MetricsContainer)
    expose_base_metrics(metrics_container_mock, "integration", "stage", clusters)
    metrics_container_mock.set_gauge.assert_has_calls([
        call(
            RhIdpClusterCounter(
                integration="integration", ocm_environment="stage", org_id=ORG_ID_1
            ),
            value=1,
        ),
        call(
            RhIdpClusterCounter(
                integration="integration",
                ocm_environment="stage",
                org_id=ORG_ID_2,
            ),
            value=2,
        ),
    ])
