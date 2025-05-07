from collections.abc import Callable

import pytest
from pytest_httpserver import HTTPServer
from requests.exceptions import ConnectionError

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
from reconcile.test.fixtures import Fixtures
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_document_manager import SLODetails, SLODocumentManager


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("slo_document_manager")


@pytest.fixture
def prometheus_query_response(
    set_httpserver_responses_based_on_fixture: Callable, fx: Callable
) -> None:
    set_httpserver_responses_based_on_fixture(
        fx=fx,
        paths=[
            "/api/v1/query",
        ],
    )


def test_slo_details_manager_positive(
    secret_reader: SecretReaderBase,
    prometheus_query_response: None,
    httpserver: HTTPServer,
) -> None:
    slo_manager = SLODocumentManager(
        secret_reader=secret_reader,
        slo_documents=[
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
                                prometheusUrl=httpserver.url_for(""),
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
    )
    slos = slo_manager.get_current_slo_list()
    assert slos == [
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
            current_slo_value=0.9999,
        )
    ]


def test_slo_details_manager_connection_error(secret_reader: SecretReaderBase) -> None:
    slo_manager = SLODocumentManager(
        secret_reader=secret_reader,
        slo_documents=[
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
                                prometheusUrl="https://test_from_ul",
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
    )
    with pytest.raises(ConnectionError):
        slo_manager.get_current_slo_list()
