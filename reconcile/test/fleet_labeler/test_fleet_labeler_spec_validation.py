import pytest

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.integration import (
    FleetLabelerIntegration,
)
from reconcile.fleet_labeler.validate import (
    MatchLabelsNotUniqueError,
    OCMAccessTokenClientIdMissing,
    OCMAccessTokenClientSecretMissing,
    OCMAccessTokenUrlMissing,
)
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
)


def test_valid_spec(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    dependencies.label_specs_by_name = {default_label_spec.name: default_label_spec}
    integration.reconcile(dependencies=dependencies)


def test_missing_client_id(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    default_label_spec.ocm.access_token_client_id = None
    dependencies.label_specs_by_name = {default_label_spec.name: default_label_spec}
    with pytest.raises(OCMAccessTokenClientIdMissing):
        integration.reconcile(dependencies=dependencies)


def test_missing_client_secret(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    default_label_spec.ocm.access_token_client_secret = None
    dependencies.label_specs_by_name = {default_label_spec.name: default_label_spec}
    with pytest.raises(OCMAccessTokenClientSecretMissing):
        integration.reconcile(dependencies=dependencies)


def test_missing_token_url(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    default_label_spec.ocm.access_token_url = None
    dependencies.label_specs_by_name = {default_label_spec.name: default_label_spec}
    with pytest.raises(OCMAccessTokenUrlMissing):
        integration.reconcile(dependencies=dependencies)


def test_non_unique_match_labels(
    integration: FleetLabelerIntegration,
    dependencies: Dependencies,
    default_label_spec: FleetLabelsSpecV1,
) -> None:
    default_label_spec.label_defaults.append(default_label_spec.label_defaults[0])
    dependencies.label_specs_by_name = {default_label_spec.name: default_label_spec}
    with pytest.raises(MatchLabelsNotUniqueError):
        integration.reconcile(dependencies=dependencies)
