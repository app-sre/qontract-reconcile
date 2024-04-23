from collections.abc import Callable, Mapping

from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.state import IntegrationState
from reconcile.utils.state import State


def test_s3_exporter(
    state: State, publisher_builder: Callable[[Mapping], Publisher]
) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    publishers = [
        publisher_builder({
            "saas_name": "saas-1",
            "resource_template_name": "template-1",
            "namespace_name": "namespace-1",
            "cluster_name": "cluster-1",
            "target_name": "target-1",
            "commit_sha": "123",
            "deployment_info": {"channel-1": True},
        })
    ]

    expected = {
        "/saas-1/template-1/target-1/cluster-1/namespace-1/True": {
            "commit_sha": "123",
            "deployment_state": "success",
        }
    }

    integration_state.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(  # type: ignore[attr-defined]
        key="publisher-data.json", value=expected, force=True
    )


def test_publisher_data_exporter_failed_deployment(
    state: State,
    publisher_builder: Callable[[Mapping], Publisher],
) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    publishers = [
        publisher_builder({
            "saas_name": "saas-1",
            "resource_template_name": "template-1",
            "namespace_name": "namespace-1",
            "cluster_name": "cluster-1",
            "commit_sha": "123",
            "deployment_info": {"channel-1": False, "channel-2": None},
        })
    ]

    expected = {
        "/saas-1/template-1/None/cluster-1/namespace-1/True": {
            "commit_sha": "123",
            "deployment_state": "failed",
        }
    }

    integration_state.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(  # type: ignore[attr-defined]
        key="publisher-data.json", value=expected, force=True
    )


def test_publisher_data_exporter_missing_deployment(
    state: State,
    publisher_builder: Callable[[Mapping], Publisher],
) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    publishers = [
        publisher_builder({
            "saas_name": "saas-1",
            "resource_template_name": "template-1",
            "namespace_name": "namespace-1",
            "cluster_name": "cluster-1",
            "commit_sha": "123",
            "deployment_info": {"channel-1": None},
        })
    ]

    expected = {
        "/saas-1/template-1/None/cluster-1/namespace-1/True": {
            "commit_sha": "123",
            "deployment_state": "missing",
        }
    }

    integration_state.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(  # type: ignore[attr-defined]
        key="publisher-data.json", value=expected, force=True
    )


def test_publisher_data_export_multiple(
    state: State,
    publisher_builder: Callable[[Mapping], Publisher],
) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    publishers = [
        publisher_builder({
            "saas_name": "saas-1",
            "resource_template_name": "template-1",
            "namespace_name": "namespace-1",
            "cluster_name": "cluster-1",
            "commit_sha": "123",
            "deployment_info": {"channel-1": True},
        }),
        publisher_builder({
            "saas_name": "saas-2",
            "resource_template_name": "template-2",
            "namespace_name": "namespace-2",
            "cluster_name": "cluster-2",
            "commit_sha": "456",
            "deployment_info": {"channel-2": False},
        }),
    ]

    expected = {
        "/saas-1/template-1/None/cluster-1/namespace-1/True": {
            "commit_sha": "123",
            "deployment_state": "success",
        },
        "/saas-2/template-2/None/cluster-2/namespace-2/True": {
            "commit_sha": "456",
            "deployment_state": "failed",
        },
    }

    integration_state.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(  # type: ignore[attr-defined]
        key="publisher-data.json", value=expected, force=True
    )


def test_publisher_data_exporter_dry_run(state: State) -> None:
    integration_state = IntegrationState(state=state, dry_run=True)
    integration_state.export_publisher_data(publishers=[])
    state.add.assert_not_called()  # type: ignore[attr-defined]
