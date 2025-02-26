from collections.abc import Callable

import pytest

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.integration import (
    FleetLabelerIntegration,
)
from reconcile.fleet_labeler.vcs import Gitlab404Error
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


def test_fleet_labeler_dry_run_new_file_spec(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We are in dry-run mode.
    OCM API returns 1 cluster.
    The VCS returns 404 for current content, because the file is new and not in main yet.

    We expect the MR to pass gently, without calling further VCS operations.
    """
    dependencies.vcs = build_vcs(error=Gitlab404Error())
    dependencies.dry_run = True
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("0_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[
            build_cluster(
                name="cluster_name",
                uid="cluster_id",
                subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
            ),
        ],
    )
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: ocm_client,
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()
    ocm_client.add_subscription_label.assert_not_called()
    ocm_client.update_subscription_label.assert_not_called()


def test_fleet_labeler_dry_run_existing_file_spec(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We are in dry-run mode.
    Labels and cluster inventory are not in synch.

    We expect that there are no calls to update/add labels since we are in dry-run.
    We expect no calls to update the inventory.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
    dependencies.dry_run = True
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("1_cluster.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[
            build_cluster(
                name="cluster_name",
                uid="123",
                subscription_labels={
                    "sre-capabilities.dtp.managed-labels": "true",
                    # Note, this value is not in synch with the spec
                    "sre-capabilities.dtp.tenant": "BadValue",
                },
            ),
            # A new cluster that is not part of inventory yet
            build_cluster(
                name="new_cluster_name",
                uid="456",
                subscription_labels={
                    "sre-capabilities.dtp.managed-labels": "true",
                },
            ),
        ],
    )
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: ocm_client,
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()
    ocm_client.add_subscription_label.assert_not_called()
    ocm_client.update_subscription_label.assert_not_called()


def test_fleet_labeler_no_dry_run_new_spec(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We are not in dry-run mode.
    OCM API returns 1 cluster.
    The VCS returns 404 for current content.

    We expect the run to fail, since in no dry-run mode we should never see 404.
    """
    dependencies.vcs = build_vcs(error=Gitlab404Error())
    dependencies.dry_run = False
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("0_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name",
                    uid="cluster_id",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
            ],
        )
    }

    with pytest.raises(Gitlab404Error):
        integration.reconcile(dependencies=dependencies)


def test_fleet_labeler_dry_run_other_error(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    We are in dry-run mode.
    OCM API returns 1 cluster.
    The VCS returns some none 404 error for current content.

    We expect the run to fail, since we should only catch 404s in dry-run mode.
    """
    dependencies.vcs = build_vcs(error=Exception())
    dependencies.dry_run = True
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("0_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: build_ocm_client(
            discover_clusters_by_labels=[
                build_cluster(
                    name="cluster_name",
                    uid="cluster_id",
                    subscription_labels={"sre-capabilities.dtp.managed-labels": "true"},
                ),
            ],
        )
    }

    with pytest.raises(Exception):
        integration.reconcile(dependencies=dependencies)
