from collections.abc import Callable

import pytest

from reconcile.dynatrace_token_provider.model import DynatraceAPIToken
from reconcile.dynatrace_token_provider.ocm import Cluster
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)


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
                            "name": "dtp-ingestion-token",
                            "keyNameInSecret": "dataIngestToken",
                            "scopes": [
                                "metrics.ingest",
                                "logs.ingest",
                                "events.ingest",
                            ],
                        },
                        {
                            "name": "dtp-operator-token",
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
def default_cluster() -> Cluster:
    return Cluster(
        id="cluster_a",
        external_id="external_id_a",
        organization_id="ocm_org_id_a",
        dt_tenant="dt_tenant_a",
        token_spec_name="default",
        is_hcp=False,
    )
