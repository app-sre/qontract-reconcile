from collections.abc import Callable

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.integration import (
    FleetLabelerIntegration,
)
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
)
from reconcile.test.fleet_labeler.fixtures import (
    build_cluster,
    build_metrics,
    build_ocm_client,
    build_vcs,
    get_fixture_content,
    label_spec_data_from_fixture,
)


def test_default_label_rendering_errors(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 0 clusters in the current inventory.
    OCM API returns 2 clustes. However, 1 cluster label cannot be rendered.

    We expect an MR that desires 1 cluster in the inventory and a metric
    that shows the rendering error for the other cluster.
    """
    dependencies.vcs = build_vcs(
        content=get_fixture_content("0_clusters_no_defaults.yaml")
    )
    dependencies.metrics = build_metrics()
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("0_clusters_no_defaults.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name",
                    uid="123",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
                build_cluster(
                    name="cluster_name_2",
                    uid="456",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
            ],
            cluster_labels={
                "123": {
                    "cluster-type": "other",
                    "cluster-sector": "other",
                },
                "456": {
                    "cluster-type": "does-not-exist",
                    "cluster-sector": "does-not-exist",
                },
            },
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="data/test.yaml",
        content=f"{get_fixture_content('1_cluster_no_defaults.yaml')}\n",
    )
    dependencies.metrics.set_label_rendering_error_gauge.assert_called_once_with(
        ocm_name="ocm_test",
        spec_name="hypershift-cluster-subscription-labels-integration",
        value=1,
    )


def test_competing_label_matchers(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 1 cluster in the current inventory.
    OCM API returns 4 completely different clusters for 2 different default labels.
    2 of the returned clusters matches 2 subscription label matchers, which means
    that defaultLabels will compete. This must not happen -> we want to neglect these
    clusters and print an error / increase error counter metric.

    We expect an MR that deletes the current cluster and adds the 2 new clusters.
    We expect the 3rd and 4th cluster to be neglected and counted towards error metric.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("1_cluster.yaml")
    )
    dependencies.metrics = build_metrics()
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name_1",
                    uid="456",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
                build_cluster(
                    name="cluster_name_2",
                    uid="789",
                    # Note, this is the filter for the 2nd default label
                    subscription_labels={"sre-capabilities.dtp.other-label": "true"},
                ),
                build_cluster(
                    name="cluster_name_3",
                    uid="1011",
                    # Note, this cluster fits both label matchers
                    subscription_labels={
                        "sre-capabilities.dtp.managed-labels": "true",
                        "sre-capabilities.dtp.other-label": "true",
                    },
                ),
                build_cluster(
                    name="cluster_name_4",
                    uid="1213",
                    # Note, this cluster fits both label matchers
                    subscription_labels={
                        "sre-capabilities.dtp.managed-labels": "true",
                        "sre-capabilities.dtp.other-label": "true",
                    },
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="data/test.yaml",
        content=f"{get_fixture_content('2_clusters.yaml')}\n",
    )
    dependencies.metrics.set_duplicate_cluster_matches_gauge.assert_called_once_with(
        ocm_name="ocm_test",
        spec_name="hypershift-cluster-subscription-labels-integration",
        value=2,
    )
