from collections.abc import Callable

import pytest

from reconcile.dynatrace_token_provider.dependencies import Dependencies
from reconcile.dynatrace_token_provider.integration import (
    DynatraceTokenProviderIntegration,
)
from reconcile.dynatrace_token_provider.validate import (
    MAX_TOKEN_NAME_LENGTH,
    KeyNameNotUniqueInSecretError,
    SecretNotUniqueError,
    TokenNameNotUniqueInSecretError,
    TokenNameTooLongError,
)
from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
)


def test_dtp_spec_validation_valid_spec(
    default_integration: DynatraceTokenProviderIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    specs = {
        "valid_spec": gql_class_factory(
            DynatraceTokenProviderTokenSpecV1,
            {
                "name": "valid_spec",
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
    }

    dependencies.token_spec_by_name = specs
    default_integration.reconcile(dry_run=False, dependencies=dependencies)


def test_dtp_spec_validation_secret_not_unique_error(
    default_integration: DynatraceTokenProviderIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    specs = {
        "valid_spec": gql_class_factory(
            DynatraceTokenProviderTokenSpecV1,
            {
                "name": "valid_spec",
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
                                ],
                            },
                        ],
                    },
                    {
                        # This is a re-definition of the previous secret
                        "name": "dynatrace-token-dtp",
                        "namespace": "dynatrace",
                        "tokens": [
                            {
                                "name": "other-token",
                                "keyNameInSecret": "dataIngestToken",
                                "scopes": [
                                    "metrics.ingest",
                                ],
                            },
                        ],
                    },
                ],
            },
        )
    }

    dependencies.token_spec_by_name = specs
    with pytest.raises(SecretNotUniqueError):
        default_integration.reconcile(dry_run=False, dependencies=dependencies)


def test_dtp_spec_validation_token_not_unique_error(
    default_integration: DynatraceTokenProviderIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    specs = {
        "valid_spec": gql_class_factory(
            DynatraceTokenProviderTokenSpecV1,
            {
                "name": "valid_spec",
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
                                ],
                            },
                            {
                                # We re-use the same name within the same secret
                                "name": "ingestion-token",
                                "keyNameInSecret": "otherKey",
                                "scopes": [
                                    "metrics.ingest",
                                ],
                            },
                        ],
                    },
                ],
            },
        )
    }

    dependencies.token_spec_by_name = specs
    with pytest.raises(TokenNameNotUniqueInSecretError):
        default_integration.reconcile(dry_run=False, dependencies=dependencies)


def test_dtp_spec_validation_key_name_not_unique_error(
    default_integration: DynatraceTokenProviderIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    specs = {
        "valid_spec": gql_class_factory(
            DynatraceTokenProviderTokenSpecV1,
            {
                "name": "valid_spec",
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
                                ],
                            },
                            {
                                "name": "other-ingestion-token",
                                # We re-use the same key within the same secret
                                "keyNameInSecret": "dataIngestToken",
                                "scopes": [
                                    "metrics.ingest",
                                ],
                            },
                        ],
                    },
                ],
            },
        )
    }

    dependencies.token_spec_by_name = specs
    with pytest.raises(KeyNameNotUniqueInSecretError):
        default_integration.reconcile(dry_run=False, dependencies=dependencies)


def test_dtp_spec_validation_token_name_too_long_error(
    default_integration: DynatraceTokenProviderIntegration,
    dependencies: Dependencies,
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecV1],
) -> None:
    specs = {
        "valid_spec": gql_class_factory(
            DynatraceTokenProviderTokenSpecV1,
            {
                "name": "valid_spec",
                "ocm_org_ids": ["ocm_org_id_a"],
                "secrets": [
                    {
                        "name": "dynatrace-token-dtp",
                        "namespace": "dynatrace",
                        "tokens": [
                            {
                                # Name too long for Dynatrace API
                                "name": f"long-name-{['a'] * MAX_TOKEN_NAME_LENGTH}",
                                "keyNameInSecret": "dataIngestToken",
                                "scopes": [
                                    "metrics.ingest",
                                ],
                            },
                        ],
                    },
                ],
            },
        )
    }

    dependencies.token_spec_by_name = specs
    with pytest.raises(TokenNameTooLongError):
        default_integration.reconcile(dry_run=False, dependencies=dependencies)
