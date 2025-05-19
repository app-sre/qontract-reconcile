from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.saas_slo_document import (
    AppV1,
    ClusterV1,
    NamespaceV1,
    SLODocument,
    SLODocumentSLOSLOParametersV1,
    SLODocumentSLOV1,
    SLONamespacesV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.saas_auto_promotions_manager.subscriber import (
    Subscriber,
)
from reconcile.utils.slo_document_manager import SLODetails


def test_slo_gatekeeping_no_slos_breached(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    mocker: MockerFixture,
) -> None:
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
        "SLOS": [
            SLODocument(
                name="test_positive_slo_doc",
                namespaces=[
                    SLONamespacesV1(
                        prometheusAccess=None,
                        SLONamespace=None,
                        namespace=NamespaceV1(
                            name="test_ns_name",
                            app=AppV1(
                                name="test",
                            ),
                            cluster=ClusterV1(
                                name="test_cls",
                                automationToken=VaultSecret(
                                    path="some/test/path",
                                    field="some-field",
                                    version=None,
                                    format=None,
                                ),
                                prometheusUrl="https://prom-url.com",
                                spec=None,
                            ),
                        ),
                    )
                ],
                slos=[
                    SLODocumentSLOV1(
                        name="test_slo_name",
                        expr="some_test_expr",
                        SLIType="availability",
                        SLOParameters=SLODocumentSLOSLOParametersV1(
                            window="28d",
                        ),
                        SLOTarget=0.95,
                        SLOTargetUnit="percent_0_1",
                    ),
                ],
            )
        ],
    })
    mocker.patch(
        "reconcile.saas_auto_promotions_manager.subscriber.SLODocumentManager.get_breached_slos"
    ).return_value = []
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_slo_gatekeeping_slos_breached(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    mocker: MockerFixture,
) -> None:
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
        "SLOS": [
            SLODocument(
                name="test_positive_slo_doc",
                namespaces=[
                    SLONamespacesV1(
                        prometheusAccess=None,
                        SLONamespace=None,
                        namespace=NamespaceV1(
                            name="test_ns_name",
                            app=AppV1(
                                name="test",
                            ),
                            cluster=ClusterV1(
                                name="test_cls",
                                automationToken=VaultSecret(
                                    path="some/test/path",
                                    field="some-field",
                                    version=None,
                                    format=None,
                                ),
                                prometheusUrl="https://prom-url.com",
                                spec=None,
                            ),
                        ),
                    )
                ],
                slos=[
                    SLODocumentSLOV1(
                        name="test_slo_name",
                        expr="some_test_expr",
                        SLIType="availability",
                        SLOParameters=SLODocumentSLOSLOParametersV1(
                            window="28d",
                        ),
                        SLOTarget=0.95,
                        SLOTargetUnit="percent_0_1",
                    ),
                ],
            )
        ],
    })
    mocker.patch(
        "reconcile.saas_auto_promotions_manager.subscriber.SLODocumentManager.get_breached_slos"
    ).return_value = [
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
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_slo_gatekeeping_slos_breached_but_hotfix(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    mocker: MockerFixture,
) -> None:
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
        "SLOS": [
            SLODocument(
                name="test_positive_slo_doc",
                namespaces=[
                    SLONamespacesV1(
                        prometheusAccess=None,
                        SLONamespace=None,
                        namespace=NamespaceV1(
                            name="test_ns_name",
                            app=AppV1(
                                name="test",
                            ),
                            cluster=ClusterV1(
                                name="test_cls",
                                automationToken=VaultSecret(
                                    path="some/test/path",
                                    field="some-field",
                                    version=None,
                                    format=None,
                                ),
                                prometheusUrl="https://prom-url.com",
                                spec=None,
                            ),
                        ),
                    )
                ],
                slos=[
                    SLODocumentSLOV1(
                        name="test_slo_name",
                        expr="some_test_expr",
                        SLIType="availability",
                        SLOParameters=SLODocumentSLOSLOParametersV1(
                            window="28d",
                        ),
                        SLOTarget=0.95,
                        SLOTargetUnit="percent_0_1",
                    ),
                ],
            )
        ],
    })
    mocker.patch(
        "reconcile.saas_auto_promotions_manager.subscriber.SLODocumentManager.get_breached_slos"
    ).return_value = [
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
    subscriber.compute_desired_state()

    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []
