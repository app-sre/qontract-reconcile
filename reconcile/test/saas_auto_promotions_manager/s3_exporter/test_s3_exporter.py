import json
from collections.abc import Callable, Mapping
from unittest.mock import create_autospec

from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.s3_exporter import S3Exporter
from reconcile.utils.state import State


def test_s3_exporter(publisher_builder: Callable[[Mapping], Publisher]):
    state = create_autospec(spec=State)
    s3_exporter = S3Exporter(state=state, dry_run=False)

    publishers = [
        publisher_builder({
            "saas_name": "saas-1",
            "resource_template_name": "template-1",
            "namespace_name": "namespace-1",
            "cluster_name": "cluster-1",
            "commit_sha": "123",
            "deployment_info": {"channel-1": True},
        })
    ]

    expected = json.dumps({
        "saas-1/template-1/cluster-1/namespace-1": {
            "commit_sha": "123",
            "deployment_state": "success",
        }
    })

    s3_exporter.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(
        key="publisher-data.json", value=expected, force=True
    )


def test_s3_exporter_failed_deployment(
    publisher_builder: Callable[[Mapping], Publisher],
):
    state = create_autospec(spec=State)
    s3_exporter = S3Exporter(state=state, dry_run=False)

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

    expected = json.dumps({
        "saas-1/template-1/cluster-1/namespace-1": {
            "commit_sha": "123",
            "deployment_state": "failed",
        }
    })

    s3_exporter.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(
        key="publisher-data.json", value=expected, force=True
    )


def test_s3_exporter_missing_deployment(
    publisher_builder: Callable[[Mapping], Publisher],
):
    state = create_autospec(spec=State)
    s3_exporter = S3Exporter(state=state, dry_run=False)

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

    expected = json.dumps({
        "saas-1/template-1/cluster-1/namespace-1": {
            "commit_sha": "123",
            "deployment_state": "missing",
        }
    })

    s3_exporter.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(
        key="publisher-data.json", value=expected, force=True
    )


def test_s3_export_multiple(
    publisher_builder: Callable[[Mapping], Publisher],
) -> None:
    state = create_autospec(spec=State)
    s3_exporter = S3Exporter(state=state, dry_run=False)

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

    expected = json.dumps({
        "saas-1/template-1/cluster-1/namespace-1": {
            "commit_sha": "123",
            "deployment_state": "success",
        },
        "saas-2/template-2/cluster-2/namespace-2": {
            "commit_sha": "456",
            "deployment_state": "failed",
        },
    })

    s3_exporter.export_publisher_data(publishers=publishers)
    state.add.assert_called_once_with(
        key="publisher-data.json", value=expected, force=True
    )


def test_exporter_dry_run() -> None:
    state = create_autospec(spec=State)
    s3_exporter = S3Exporter(state=state, dry_run=True)
    s3_exporter.export_publisher_data(publishers=[])
    state.add.assert_not_called()
