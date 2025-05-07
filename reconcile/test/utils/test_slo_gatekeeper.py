from pytest_mock import MockFixture

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
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_document_manager import SLODetails
from reconcile.utils.slo_gatekeeper import SLOGateKeeper


def test_slo_gatekeeper_positive(
    secret_reader: SecretReaderBase, mocker: MockFixture
) -> None:
    slo_documents: list[SLODocument] = [
        SLODocument(
            name="test_saas_doc",
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
                            prometheusUrl="http://test-prom-url",
                            spec=None,
                        ),
                    ),
                ),
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
        ),
    ]
    get_slo_value = mocker.patch(
        "reconcile.utils.slo_document_manager.SLODocumentManager._get_current_slo_details_list"
    )
    get_slo_value.return_value = [
        SLODetails(
            namespace_name="test_ns_name",
            service_name="test",
            cluster_name="test_cls",
            slo_document_name="test_slo_name",
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
            current_slo_value=0.99,
        )
    ]
    slo_gate_keeper = SLOGateKeeper(
        secret_reader=secret_reader, slo_documents=slo_documents
    )
    assert slo_gate_keeper.get_breached_slos() == []


def test_slo_gatekeeper_slo_breached(
    secret_reader: SecretReaderBase, mocker: MockFixture
) -> None:
    slo_documents: list[SLODocument] = [
        SLODocument(
            name="test_saas_doc",
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
                            prometheusUrl="http://test-prom-url",
                            spec=None,
                        ),
                    ),
                ),
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
        ),
    ]
    get_slo_value = mocker.patch(
        "reconcile.utils.slo_document_manager.SLODocumentManager._get_current_slo_details_list"
    )
    get_slo_value.return_value = [
        SLODetails(
            namespace_name="test_ns_name",
            service_name="test_service",
            cluster_name="test_cls",
            slo_document_name="test_slo_name",
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
            current_slo_value=0.92,
        )
    ]
    slo_gate_keeper = SLOGateKeeper(
        secret_reader=secret_reader, slo_documents=slo_documents
    )
    assert slo_gate_keeper.get_breached_slos() == [
        SLODetails(
            namespace_name="test_ns_name",
            service_name="test_service",
            slo_document_name="test_slo_name",
            cluster_name="test_cls",
            slo=SLODocumentSLOV1(
                name="test_slo_name",
                expr="some_test_expr",
                SLIType="availability",
                SLOParameters=SLODocumentSLOSLOParametersV1(window="28d"),
                SLOTarget=0.95,
                SLOTargetUnit="percent_0_1",
            ),
            current_slo_value=0.92,
        )
    ]
