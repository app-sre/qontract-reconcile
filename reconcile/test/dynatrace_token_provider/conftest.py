from collections.abc import Callable

import pytest

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken
from reconcile.dynatrace_token_provider.ocm import OCMCluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)
from reconcile.utils.secret_reader import SecretReaderBase


@pytest.fixture
def default_token_spec(
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> DynatraceTokenProviderTokenSpecV1:
    return gql_class_factory(
        DynatraceTokenProviderTokenSpecV1,
        {
            "name": "default",
            "ocm_org_ids": ["ocm_org_id_a"],
            "secrets": [
                {
                    "name": "dynatrace-token-dtp",
                    "namespace": "dynatrace",
                    "tokens": [
                        {
                            "name": "ingestion-token",
                            "keyNameInSecret": "dataIngestToken",
                            "scopes": [
                                "metrics.ingest",
                                "logs.ingest",
                                "events.ingest",
                            ],
                        },
                        {
                            "name": "operator-token",
                            "keyNameInSecret": "apiToken",
                            "scopes": [
                                "activeGateTokenManagement.create",
                                "entities.read",
                                "settings.write",
                                "settings.read",
                                "DataExport",
                                "InstallerDownload",
                            ],
                        },
                    ],
                }
            ],
        },
    )


@pytest.fixture
def default_integration() -> DynatraceTokenProviderIntegration:
    return DynatraceTokenProviderIntegration()


@pytest.fixture
def dependencies(secret_reader: SecretReaderBase) -> Dependencies:
    return Dependencies(
        secret_reader=secret_reader,
        dynatrace_client_by_tenant_id={},
        ocm_client_by_env_name={},
        token_spec_by_name={},
    )


@pytest.fixture
def default_operator_token() -> DynatraceAPIToken:
    return DynatraceAPIToken(
        id="id1",
        name="dtp-operator-token",
        token="operator123",
        secret_key="apiToken",
    )


@pytest.fixture
def default_ingestion_token() -> DynatraceAPIToken:
    return DynatraceAPIToken(
        id="id2",
        name="dtp-ingestion-token",
        token="ingest123",
        secret_key="dataIngestToken",
    )


@pytest.fixture
def default_cluster() -> OCMCluster:
    return OCMCluster(
        id="cluster_a",
        external_id="external_id_a",
        organization_id="ocm_org_id_a",
        subscription_id="sub_id",
        is_hcp=False,
        labels={
            "sre-capabilities.dtp.v2.tenant": "dt_tenant_a",
            "sre-capabilities.dtp.v2.token-spec": "default",
        },
    )


@pytest.fixture
def default_hcp_cluster() -> OCMCluster:
    return OCMCluster(
        id="cluster_a",
        external_id="external_id_a",
        organization_id="ocm_org_id_a",
        subscription_id="sub_id",
        is_hcp=True,
        labels={
            "sre-capabilities.dtp.v2.tenant": "dt_tenant_a",
            "sre-capabilities.dtp.v2.token-spec": "default",
        },
    )
