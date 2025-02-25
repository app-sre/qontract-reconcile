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


def test_subscription_label_filter(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    default_label_spec.name = "spec"
    dependencies.label_specs_by_name = {"spec": default_label_spec}

    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[],
    )
    dependencies.ocm_clients_by_label_spec_name = {"spec": ocm_client}

    integration.reconcile(dependencies=dependencies)

    ocm_client.discover_clusters_by_labels.assert_called_once_with(
        labels={"test": "true"},
    )


def test_default_label_filter(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We have 0 clusters in the current inventory.
    OCM API returns 2 clusters, but one doesnt match the default label filter.

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
                    uid="123",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
                build_cluster(
                    name="cluster_name_2",
                    uid="456",
                    # Note, the label doesnt match the filter
                    subscription_labels={
                        "sre-capabilities.dtp.managed-labels": "false"
                    },
                ),
            ],
        )
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_called_once_with(
        path="data/test.yaml",
        content=f"{get_fixture_content('1_cluster.yaml')}\n",
    )
