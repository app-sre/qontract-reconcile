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

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()


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
