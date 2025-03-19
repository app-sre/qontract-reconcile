import pytest
from pytest_mock import MockFixture

from reconcile.gql_definitions.fragments.saas_slo_document import (
    AppV1,
    ClusterV1,
    NamespaceV1,
    SaasSLODocument,
    SLODocumentSLOSLOParametersV1,
    SLODocumentSLOV1,
    SLONamespacesV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_gatekeeper import SLOGateKeeper


@pytest.fixture
def secret_reader(mocker) -> None:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


def test_slo_gatekeeper_positive(secret_reader: SecretReaderBase, mocker: MockFixture):
    slo_documents: list[SaasSLODocument] = [
        SaasSLODocument(
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
    get_SLO_value = mocker.patch(
        "reconcile.utils.slo_gatekeeper.SLODetails.get_SLO_value"
    )
    get_SLO_value.return_value = 0.96
    slo_gate_keeper = SLOGateKeeper(
        secret_reader=secret_reader, slo_documents=slo_documents
    )
    assert not slo_gate_keeper.is_slo_breached()


def test_slo_gatekeeper_(secret_reader: SecretReaderBase, mocker: MockFixture):
    slo_documents: list[SaasSLODocument] = [
        SaasSLODocument(
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
                    SLOTarget=0.99,
                    SLOTargetUnit="percent_0_1",
                ),
            ],
        ),
    ]
    get_SLO_value = mocker.patch(
        "reconcile.utils.slo_gatekeeper.SLODetails.get_SLO_value"
    )
    get_SLO_value.return_value = 0.95
    slo_gate_keeper = SLOGateKeeper(secret_reader=secret_reader, slos=slo_documents)
    assert slo_gate_keeper.is_slo_breached()
