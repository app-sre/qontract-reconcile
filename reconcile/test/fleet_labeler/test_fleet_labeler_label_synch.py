from collections.abc import Callable
from unittest.mock import call

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


def test_add_new_labels(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    Our cluster inventory has 1 cluster and is in synch.
    The desired clusters labels do not exist.

    We expect calls to add new subscription labels for the cluster.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
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
                },
            ),
        ],
    )
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: ocm_client,
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()
    expected_label_calls = [
        call(
            subscription_id="123",
            key="sre-capabilities.dtp.spec.tenant",
            value="tenantabc",
        ),
        call(
            subscription_id="123",
            key="sre-capabilities.dtp.spec.tokenSpec",
            value="hypershift-management-cluster-v1",
        ),
    ]
    ocm_client.add_subscription_label.assert_has_calls(
        expected_label_calls, any_order=True
    )
    assert ocm_client.add_subscription_label.call_count == 2
    ocm_client.update_subscription_label.assert_not_called()


def test_update_existing_labels(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    Our cluster inventory has 1 cluster and is in synch.
    The desired clusters labels exist but the values dont match.

    We expect calls to update existing subscription labels for the cluster.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
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
                    "sre-capabilities.dtp.spec.tenant": "badvalue",
                    "sre-capabilities.dtp.spec.tokenSpec": "badvalue",
                },
            ),
        ],
    )
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: ocm_client,
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()
    expected_label_calls = [
        call(
            subscription_id="123",
            key="sre-capabilities.dtp.spec.tenant",
            value="tenantabc",
        ),
        call(
            subscription_id="123",
            key="sre-capabilities.dtp.spec.tokenSpec",
            value="hypershift-management-cluster-v1",
        ),
    ]
    ocm_client.update_subscription_label.assert_has_calls(
        expected_label_calls, any_order=True
    )
    assert ocm_client.update_subscription_label.call_count == 2
    ocm_client.add_subscription_label.assert_not_called()


def test_update_and_add_labels_on_multiple_clusters(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    Our cluster inventory has 2 clusters and is in synch.
    The desired clusters labels part-wise exist but the values dont match.

    We expect calls to update existing subscription labels for the cluster.
    We also expect calls to add new missing subscription labels.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("2_clusters.yaml"))
    spec = gql_class_factory(
        FleetLabelsSpecV1, label_spec_data_from_fixture("2_clusters.yaml")
    )
    dependencies.label_specs_by_name = {spec.name: spec}
    ocm_client = build_ocm_client(
        discover_clusters_by_labels=[
            build_cluster(
                name="cluster_name_1",
                uid="456",
                subscription_labels={
                    "sre-capabilities.dtp.managed-labels": "true",
                    "sre-capabilities.dtp.spec.tenant": "badvalue",
                    # Note, missing tokenSpec label
                },
            ),
            build_cluster(
                name="cluster_name_2",
                uid="789",
                subscription_labels={
                    "sre-capabilities.dtp.managed-labels": "true",
                    "sre-capabilities.dtp.spec.tokenSpec": "badvalue",
                    # Note, missing tenant label
                },
            ),
        ],
    )
    dependencies.ocm_clients_by_label_spec_name = {
        spec.name: ocm_client,
    }

    integration.reconcile(dependencies=dependencies)

    dependencies.vcs.open_merge_request.assert_not_called()

    expected_add_label_calls = [
        call(
            subscription_id="789",
            key="sre-capabilities.dtp.spec.tenant",
            value="tenantother1",
        ),
        call(
            subscription_id="456",
            key="sre-capabilities.dtp.spec.tokenSpec",
            value="hypershift-management-cluster-v1",
        ),
    ]
    ocm_client.add_subscription_label.assert_has_calls(
        expected_add_label_calls, any_order=True
    )
    assert ocm_client.add_subscription_label.call_count == 2

    expected_update_label_calls = [
        call(
            subscription_id="456",
            key="sre-capabilities.dtp.spec.tenant",
            value="tenantabc",
        ),
        call(
            subscription_id="789",
            key="sre-capabilities.dtp.spec.tokenSpec",
            value="specother1",
        ),
    ]
    ocm_client.update_subscription_label.assert_has_calls(
        expected_update_label_calls, any_order=True
    )
    assert ocm_client.update_subscription_label.call_count == 2


def test_no_diff(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> None:
    """
    Our cluster inventory has 1 cluster and is in synch.
    The desired clusters labels exist and are in synch.

    We do not expect any calls.
    """
    dependencies.vcs = build_vcs(content=get_fixture_content("1_cluster.yaml"))
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
                    "sre-capabilities.dtp.spec.tenant": "tenantabc",
                    "sre-capabilities.dtp.spec.tokenSpec": "hypershift-management-cluster-v1",
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
