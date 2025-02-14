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
    build_ocm_client,
    build_vcs,
    get_fixture_content,
    label_spec_data_from_fixture,
)


def test_add_new_cluster(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 0 clusters in the current inventory.
    OCM API returns 1 cluster.

    We expect an MR that desires 1 cluster in the inventory.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("0_clusters.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("0_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name",
                    cluster_id="cluster_id",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="test.yaml",
        content=f"{get_fixture_content('1_cluster.yaml')}\n",
    )


def test_delete_cluster(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 1 cluster in the current inventory.
    OCM API returns 0 clusters.

    We expect an MR that desires 0 clusters in the inventory.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("1_cluster.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="test.yaml",
        content=f"{get_fixture_content('0_clusters.yaml')}\n",
    )


def test_delete_and_add_cluster_multi_default_labels(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 1 cluster in the current inventory.
    OCM API returns 2 completely different clusters for 2 different default labels.

    We expect an MR that deletes the current cluster and adds the 2 new clusters.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("1_cluster.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name_1",
                    cluster_id="cluster_id_1",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
                build_cluster(
                    name="cluster_name_2",
                    cluster_id="cluster_id_2",
                    # Note, this is the filter for the 2nd default label
                    subscription_labels={"sre-capabilities.dtp.other-label": "true"},
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="test.yaml",
        content=f"{get_fixture_content('2_clusters.yaml')}\n",
    )


def test_no_change(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 2 clusters in the current inventory. Both clusters belong to different default label specs.
    OCM API detects the same clusters now.

    We expect no MR.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("2_clusters.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("2_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name_1",
                    cluster_id="cluster_id_1",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
                build_cluster(
                    name="cluster_name_2",
                    cluster_id="cluster_id_2",
                    subscription_labels={"sre-capabilities.dtp.other-label": "true"},
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()


def test_no_reconcile_on_label_change(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 1 cluster in the current inventory.
    OCM API detects the same cluster, however, its labels differ from the default labels.

    We expect no MR, since we should not react on manual label changes.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("1_cluster.yaml")
    )
    # Lets tweak the current label a little
    spec.clusters[0].subscription_labels = {"changed": "label"}
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name",
                    cluster_id="cluster_id",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()
