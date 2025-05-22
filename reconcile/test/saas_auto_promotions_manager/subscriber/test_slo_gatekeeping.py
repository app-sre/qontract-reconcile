from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any
from unittest.mock import create_autospec

from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.saas_slo_document import (
    SLODocumentSLOSLOParametersV1,
    SLODocumentSLOV1,
)
from reconcile.saas_auto_promotions_manager.subscriber import (
    Subscriber,
)
from reconcile.utils.slo_document_manager import SLODetails, SLODocumentManager


def test_slo_gatekeeping_no_slos_breached(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    slo_document_manager = create_autospec(SLODocumentManager)
    slo_document_manager.get_breached_slos.return_value = []
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
        "SLO_DOCUMENT_MANAGER": slo_document_manager,
    })
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_slo_gatekeeping_slos_breached(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    slo_document_manager = create_autospec(SLODocumentManager)
    slo_document_manager.get_breached_slos.return_value = [
        SLODetails(
            namespace_name="test_ns_name",
            slo_document_name="test_positive_slo_doc",
            cluster_name="test_cls",
            slo=SLODocumentSLOV1(
                name="test_slo_name",
                expr="some_test_expr",
                SLIType="availability",
                SLOParameters=SLODocumentSLOSLOParametersV1(
                    window="28d",
                ),
                SLOTarget=0.95,
                SLOTargetUnit="percent_0_1",
            ),
            service_name="test",
            current_slo_value=0.9799,
        )
    ]
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
        "SLO_DOCUMENT_MANAGER": slo_document_manager,
    })
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_slo_gatekeeping_slos_breached_but_hotfix(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    mocker: MockerFixture,
) -> None:
    slo_document_manager = create_autospec(SLODocumentManager)
    slo_document_manager.get_breached_slos.return_value = [
        SLODetails(
            namespace_name="test_ns_name",
            slo_document_name="test_positive_slo_doc",
            cluster_name="test_cls",
            slo=SLODocumentSLOV1(
                name="test_slo_name",
                expr="some_test_expr",
                SLIType="availability",
                SLOParameters=SLODocumentSLOSLOParametersV1(
                    window="28d",
                ),
                SLOTarget=0.95,
                SLOTargetUnit="percent_0_1",
            ),
            service_name="test",
            current_slo_value=0.9799,
        )
    ]
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
        "HOTFIX_VERSIONS": {"new_sha"},
        "SLO_DOCUMENT_MANAGER": slo_document_manager,
    })
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []
