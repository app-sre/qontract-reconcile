from typing import Optional

import pytest
from pydantic import ValidationError
from pytest_mock import MockerFixture

from reconcile.aus import advanced_upgrade_service
from reconcile.aus.advanced_upgrade_service import (
    ClusterUpgradePolicyLabelSet,
    OrganizationLabelSet,
    _build_org_upgrade_spec,
    _build_org_upgrade_specs_for_ocm_env,
    _build_policy_from_labels,
    _discover_clusters,
    _expose_cluster_validation_errors_as_service_log,
    _get_org_labels,
    _signal_validation_issues_for_org,
    aus_label_key,
)
from reconcile.aus.models import OrganizationUpgradeSpec
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.ocm.fixtures import (
    build_label,
    build_ocm_cluster,
    build_organization_label,
)
from reconcile.utils.ocm.clusters import ClusterDetails
from reconcile.utils.ocm.labels import (
    LabelContainer,
    build_label_container,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.sre_capability_labels import build_labelset
from reconcile.utils.ocm_base_client import OCMBaseClient

#
# organization label set
#


def build_org_config_labels(
    with_blocked_versions: bool = False,
    sector_deps: Optional[dict[str, list[str]]] = None,
) -> LabelContainer:
    labels = []
    if with_blocked_versions:
        labels.append(build_label(aus_label_key("blocked-versions"), r"^.*-fc\..*$"))
    if sector_deps:
        for sector, deps in sector_deps.items():
            labels.append(
                build_label(aus_label_key(f"sector-deps.{sector}"), ",".join(deps))
            )
    return build_label_container(labels)


def test_organization_label_set_no_labels() -> None:
    labels = build_org_config_labels()
    labelset = build_labelset(labels, OrganizationLabelSet)
    assert labelset.blocked_versions is None
    assert labelset.sector_deps == {}


def test_organization_label_set_with_blocked_versions() -> None:
    labels = build_org_config_labels(with_blocked_versions=True)
    labelset = build_labelset(labels, OrganizationLabelSet)
    assert labelset.blocked_versions == [r"^.*-fc\..*$"]


def test_organization_label_set_with_sector_deps() -> None:
    labels = build_org_config_labels(sector_deps={"a": ["b", "c"], "b": ["d"]})
    labelset = build_labelset(labels, OrganizationLabelSet)
    assert labelset.sector_deps == {"a": ["b", "c"], "b": ["d"]}


def test_organization_label_set_sector_dependencies_transformation() -> None:
    labels = build_org_config_labels(sector_deps={"a": ["b", "c"], "b": ["d"]})
    labelset = build_labelset(labels, OrganizationLabelSet)
    sector_dependencies = {s.name: s for s in labelset.sector_dependencies()}

    assert sector_dependencies.keys() == {"a", "b", "c", "d"}
    assert {d.name for d in sector_dependencies["a"].dependencies or []} == {"b", "c"}
    assert {d.name for d in sector_dependencies["b"].dependencies or []} == {"d"}
    assert {d.name for d in sector_dependencies["c"].dependencies or []} == set()
    assert {d.name for d in sector_dependencies["d"].dependencies or []} == set()


#
# cluster upgrade policy label set
#


def build_cluster_upgrade_policy_labels(
    soak_days: int = 0,
    workloads: Optional[list[str]] = None,
    schedule: Optional[str] = None,
    mutexes: Optional[list[str]] = None,
    sector: Optional[str] = None,
) -> LabelContainer:
    labels = [
        build_label(aus_label_key("soak-days"), str(soak_days)),
        build_label(
            aus_label_key("workloads"),
            ",".join(workloads if workloads is not None else ["workload"]),
        ),
        build_label(aus_label_key("schedule"), schedule or "0 * * * 1-5"),
    ]
    if mutexes:
        labels.append(build_label(aus_label_key("mutexes"), ",".join(mutexes)))
    if sector:
        labels.append(build_label(aus_label_key("sector"), sector))
    return build_label_container(labels)


def test_cluster_upgrade_policy_label_set() -> None:
    labels = build_cluster_upgrade_policy_labels()
    labelset = build_labelset(labels, ClusterUpgradePolicyLabelSet)
    assert labelset.soak_days == 0
    assert labelset.workloads == ["workload"]
    assert labelset.schedule == "0 * * * 1-5"
    assert labelset.mutexes is None
    assert labelset.sector is None


def test_cluster_upgrade_policy_label_set_no_workloads() -> None:
    labels = build_cluster_upgrade_policy_labels(workloads=[])
    with pytest.raises(ValidationError):
        build_labelset(labels, ClusterUpgradePolicyLabelSet)


def test_cluster_upgrade_policy_label_set_invalid_soak_days() -> None:
    labels = build_cluster_upgrade_policy_labels(soak_days=-5)
    with pytest.raises(ValidationError):
        build_labelset(labels, ClusterUpgradePolicyLabelSet)


def test_cluster_upgrade_policy_label_set_invalid_schedule() -> None:
    labels = build_cluster_upgrade_policy_labels(schedule="0 48 * * 1-5")
    with pytest.raises(ValidationError):
        build_labelset(labels, ClusterUpgradePolicyLabelSet)


def test_build_policy_from_labels() -> None:
    policy = _build_policy_from_labels(
        build_cluster_upgrade_policy_labels(
            soak_days=5,
            workloads=["wl-1", "wl-2"],
            sector="a",
            schedule="0 * * * 1-5",
            mutexes=["m1"],
        )
    )
    assert policy.conditions.soak_days == 5
    assert policy.conditions.sector == "a"
    assert policy.conditions.mutexes == ["m1"]
    assert policy.workloads == ["wl-1", "wl-2"]
    assert policy.schedule == "0 * * * 1-5"


#
# build_org_upgrade_spec
#


@pytest.fixture
def ocm_env() -> OCMEnvironment:
    return OCMEnvironment(
        name="env",
        url="https://ocm",
        accessTokenUrl="https://sso/token",
        accessTokenClientId="client-id",
        accessTokenClientSecret=VaultSecret(
            field="client-secret", path="path", format=None, version=None
        ),
    )


@pytest.fixture
def org_labels() -> LabelContainer:
    return build_org_config_labels(with_blocked_versions=True)


def build_cluster_details(
    cluster_name: str, labels: LabelContainer, org_id: str = "org-id"
) -> ClusterDetails:
    return ClusterDetails(
        ocm_cluster=build_ocm_cluster(
            name=cluster_name, subs_id=f"{cluster_name}_subs_id"
        ),
        organization_id=org_id,
        capabilities={},
        labels=labels,
    )


def test_build_org_upgrade_spec(
    ocm_env: OCMEnvironment, org_labels: LabelContainer
) -> None:
    org_upgrade_spec = _build_org_upgrade_spec(
        ocm_env=ocm_env,
        org_id="org-id",
        clusters=[
            build_cluster_details(
                "cluster-1",
                build_cluster_upgrade_policy_labels(),
            ),
        ],
        org_labels=org_labels,
    )
    assert len(org_upgrade_spec.cluster_errors) == 0
    assert len(org_upgrade_spec.specs) == 1


def test_build_org_upgrade_spec_with_cluster_error(
    ocm_env: OCMEnvironment, org_labels: LabelContainer
) -> None:
    org_upgrade_spec = _build_org_upgrade_spec(
        ocm_env=ocm_env,
        org_id="org-id",
        clusters=[
            build_cluster_details(
                "cluster-1",
                build_cluster_upgrade_policy_labels(soak_days=-5),
            ),
        ],
        org_labels=org_labels,
    )
    assert len(org_upgrade_spec.cluster_errors) == 1
    assert len(org_upgrade_spec.specs) == 0


#
# build_org_upgrade_specs_for_ocm_env
#


def test_build_org_upgrade_specs_for_ocm_env(ocm_env: OCMEnvironment) -> None:
    org_id = "org-id"
    soak_days = 10
    cluster_details = build_cluster_details(
        cluster_name="cluster-1",
        labels=build_cluster_upgrade_policy_labels(soak_days=soak_days),
    )
    upgrade_specs = _build_org_upgrade_specs_for_ocm_env(
        ocm_env=ocm_env,
        clusters_by_org={org_id: [cluster_details]},
        labels_by_org={
            org_id: build_org_config_labels(),
        },
    )
    assert org_id in upgrade_specs

    org_spec = upgrade_specs[org_id]
    assert len(org_spec.cluster_errors) == 0
    assert len(org_spec.specs) == 1

    cluster_spec = org_spec.specs[0]
    assert cluster_spec.name == cluster_details.ocm_cluster.name
    assert cluster_spec.upgrade_policy.conditions.soak_days == soak_days


def test_build_org_upgrade_specs_for_ocm_env_with_cluster_error(
    ocm_env: OCMEnvironment,
) -> None:
    org_id = "org-id"
    cluster_details = build_cluster_details(
        cluster_name="cluster-1",
        labels=build_cluster_upgrade_policy_labels(soak_days=-10),
    )
    upgrade_specs = _build_org_upgrade_specs_for_ocm_env(
        ocm_env=ocm_env,
        clusters_by_org={org_id: [cluster_details]},
        labels_by_org={
            org_id: build_org_config_labels(),
        },
    )
    assert org_id in upgrade_specs

    org_spec = upgrade_specs[org_id]
    assert len(org_spec.cluster_errors) == 1
    assert len(org_spec.specs) == 0


#
# discover_clusters
#


def test_discover_clusters(mocker: MockerFixture) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    discover_clusters_by_labels_mock = mocker.patch.object(
        advanced_upgrade_service,
        "discover_clusters_by_labels",
        autospec=True,
    )
    discover_clusters_by_labels_mock.return_value = [
        build_cluster_details(
            cluster_name=cluster_name,
            labels=build_cluster_upgrade_policy_labels(),
            org_id=org_id,
        )
    ]

    clusters = _discover_clusters(None, "org-id")  # type: ignore

    discover_clusters_by_labels_mock.assert_called_once_with(
        ocm_api=None, label_filter=Filter().like("key", aus_label_key("%"))
    )

    assert org_id in clusters
    assert len(clusters[org_id]) == 1
    assert clusters[org_id][0].ocm_cluster.name == cluster_name


def test_discover_clusters_with_org_filter(mocker: MockerFixture) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    discover_clusters_by_labels_mock = mocker.patch.object(
        advanced_upgrade_service,
        "discover_clusters_by_labels",
        autospec=True,
    )
    discover_clusters_by_labels_mock.return_value = [
        build_cluster_details(
            cluster_name=cluster_name,
            labels=build_cluster_upgrade_policy_labels(),
            org_id=org_id,
        )
    ]

    clusters = _discover_clusters(None, "org-id")  # type: ignore
    assert org_id in clusters

    clusters = _discover_clusters(None, "another-org-id")  # type: ignore
    assert org_id not in clusters


def test_discover_clusters_without_org_filter(mocker: MockerFixture) -> None:
    org_id = "org-id"
    cluster_name = "cluster-1"

    discover_clusters_by_labels_mock = mocker.patch.object(
        advanced_upgrade_service,
        "discover_clusters_by_labels",
        autospec=True,
    )
    discover_clusters_by_labels_mock.return_value = [
        build_cluster_details(
            cluster_name=cluster_name,
            labels=build_cluster_upgrade_policy_labels(),
            org_id=org_id,
        )
    ]

    clusters = _discover_clusters(None, None)  # type: ignore

    assert org_id in clusters


#
# org_labels
#


def test_org_labels(ocm_api: OCMBaseClient, mocker: MockerFixture) -> None:
    get_organization_labels_mock = mocker.patch.object(
        advanced_upgrade_service,
        "get_organization_labels",
        autospec=True,
    )
    get_organization_labels_mock.return_value = iter(
        [build_organization_label("label", "value")]
    )

    labels = _get_org_labels(ocm_api, None)

    get_organization_labels_mock.assert_called_once_with(
        ocm_api, Filter().like("key", aus_label_key("%"))
    )

    assert len(labels) == 1
    assert labels["org-id"].get_label_value("label") == "value"


def test_org_labels_with_org_filter(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    org_id = "org-id"
    get_organization_labels_mock = mocker.patch.object(
        advanced_upgrade_service,
        "get_organization_labels",
        autospec=True,
    )
    get_organization_labels_mock.return_value = iter(
        [build_organization_label("label", "value", org_id)]
    )

    _get_org_labels(ocm_api, org_id)

    get_organization_labels_mock.assert_called_once_with(
        ocm_api, Filter().like("key", aus_label_key("%")).eq("organization_id", org_id)
    )


#
# _signal_validation_issues
#


def build_org_upgrade_specs(
    ocm_env: OCMEnvironment, cluster_error: bool = False
) -> dict[str, OrganizationUpgradeSpec]:
    org_id = "org-id"
    cluster_details = build_cluster_details(
        cluster_name="cluster-1",
        labels=build_cluster_upgrade_policy_labels(
            soak_days=(-1 if cluster_error else 1)
        ),
    )
    return _build_org_upgrade_specs_for_ocm_env(
        ocm_env=ocm_env,
        clusters_by_org={org_id: [cluster_details]},
        labels_by_org={
            org_id: build_org_config_labels(),
        },
    )


def test_signal_validation_issues_no_errors(
    ocm_env: OCMEnvironment, ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    service_log_mock = mocker.patch.object(
        advanced_upgrade_service,
        "_expose_cluster_validation_errors_as_service_log",
        autospec=True,
    )

    org_upgrade_specs = build_org_upgrade_specs(ocm_env, cluster_error=False)
    spec = org_upgrade_specs["org-id"]
    assert not spec.has_validation_errors
    _signal_validation_issues_for_org(ocm_api, org_upgrade_spec=spec)

    assert service_log_mock.call_count == 0


def test_signal_validation_issues_cluster_validation_error(
    ocm_env: OCMEnvironment, ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    service_log_mock = mocker.patch.object(
        advanced_upgrade_service,
        "_expose_cluster_validation_errors_as_service_log",
        autospec=True,
    )
    org_upgrade_specs = build_org_upgrade_specs(ocm_env, cluster_error=True)
    spec = org_upgrade_specs["org-id"]
    assert spec.has_validation_errors
    _signal_validation_issues_for_org(ocm_api, org_upgrade_spec=spec)

    assert service_log_mock.call_count == 1


#
# _expose_cluster_validation_error_to_service_log
#


def test_expose_cluster_validation_error_to_service_log(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    create_service_log_mock = mocker.patch.object(
        advanced_upgrade_service,
        "create_service_log",
        autospec=True,
    )

    cluster_uuid = "cluster-uuid"
    errors = ["sre-capabilities.aus.soak-days: must be greater than or equal to 0"]
    _expose_cluster_validation_errors_as_service_log(
        ocm_api=ocm_api, cluster_uuid=cluster_uuid, errors=errors
    )

    assert create_service_log_mock.call_count == 1


#
# utils
#


def test_aus_label_key() -> None:
    assert aus_label_key("foo") == "sre-capabilities.aus.foo"
