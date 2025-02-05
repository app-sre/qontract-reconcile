from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.integration import (
    FleetLabelerIntegration,
)
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
)
from reconcile.test.fleet_labeler.fixtures import (
    build_ocm_client,
)


# TODO: test OCMClient cluster filtering
def test_cluster_filter(
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
    ocm_client.discover_clusters_by_labels.assert_called_once_with(  # type: ignore[attr-defined]
        labels={
            "test": "true",
        },
    )
