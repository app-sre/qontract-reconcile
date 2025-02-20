from collections.abc import Callable
from unittest.mock import (
    create_autospec,
)

import pytest

from reconcile.fleet_labeler.dependencies import Dependencies
from reconcile.fleet_labeler.integration import (
    FleetLabelerIntegration,
)
from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.vcs import VCS


@pytest.fixture
def default_label_spec(
    gql_class_factory: Callable[..., FleetLabelsSpecV1],
) -> FleetLabelsSpecV1:
    return gql_class_factory(
        FleetLabelsSpecV1,
        {
            "path": "/test.yaml",
            "name": "default-spec",
            "ocm": {
                "environment": {
                    "url": "https://api.test.com",
                },
                "accessTokenClientId": "client_id",
                "accessTokenUrl": "https://test.com",
                "accessTokenClientSecret": {},
            },
            "labelDefaults": [
                {
                    "name": "all",
                    "matchSubscriptionLabels": '{"test": "true"}',
                    "subscriptionLabelTemplate": {
                        "path": {
                            "content": "test",
                        },
                        "type": "jinja2",
                        "variables": '{"test": {"test": "true"} }',
                    },
                }
            ],
            "clusters": [],
        },
    )


@pytest.fixture
def integration() -> FleetLabelerIntegration:
    return FleetLabelerIntegration()


@pytest.fixture
def dependencies(secret_reader: SecretReaderBase) -> Dependencies:
    return Dependencies(
        label_specs_by_name={},
        ocm_clients_by_label_spec_name={},
        vcs=create_autospec(spec=VCS),
        dry_run=False,
    )
