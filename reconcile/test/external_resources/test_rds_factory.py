from collections.abc import Mapping
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.external_resources.aws import AWSRdsFactory
from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceModuleConfiguration,
    ExternalResourceProvision,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.external_resources import ResourceValueResolver


@pytest.fixture
def factory() -> AWSRdsFactory:
    return AWSRdsFactory(er_inventory=Mock(), secret_reader=Mock())


DEFAULT_TIMEOUT_MINUTES = 1440
DEFAULT_EXPECTED_TIMEOUTS = {
    "create": "1435m",
    "delete": "1435m",
    "update": "1435m",
}


@pytest.mark.parametrize(
    ("reconcile_timeout_minutes", "timeouts", "expected_timeouts"),
    [
        (
            DEFAULT_TIMEOUT_MINUTES,
            {"create": "60m", "update": "60m", "delete": "60m"},
            {"create": "60m", "update": "60m", "delete": "60m"},
        ),
        (
            DEFAULT_TIMEOUT_MINUTES,
            None,
            DEFAULT_EXPECTED_TIMEOUTS,
        ),
    ],
)
def test_validate_timeouts_ok(
    reconcile_timeout_minutes: int,
    timeouts: Mapping[str, str],
    expected_timeouts: Mapping[str, str],
) -> None:
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test"},
        resource={"identifier": "test-rds", "provider": "rds", "timeouts": timeouts},
        namespace={},
    )
    module_conf = ExternalResourceModuleConfiguration(
        reconcile_timeout_minutes=reconcile_timeout_minutes
    )
    factory = AWSRdsFactory(er_inventory=Mock(), secret_reader=Mock())
    data = factory.resolve(spec, module_conf)
    resource = ExternalResource(
        data=data,
        provision=Mock(spec=ExternalResourceProvision),
    )

    factory.validate(resource, module_conf)
    assert resource.data["timeouts"] == expected_timeouts


@pytest.mark.parametrize(
    ("timeouts", "expected_value_error"),
    [
        (
            {
                "create": "125m",
            },
            r"RDS instance create timeout value 125 \(minutes\) must be lower than the module reconcile_timeout_minutes value 120.",
        ),
        (
            {
                "create": "2h",
            },
            r"RDS instance create timeout value 120 \(minutes\) must be lower than the module reconcile_timeout_minutes value 120.",
        ),
        (
            {"create": "2h30m", "update": "2h30m", "delete": "2h30m"},
            r"RDS instance create timeout value 150 \(minutes\) must be lower than the module reconcile_timeout_minutes value 120.",
        ),
        (
            {"create": "1h500s"},
            "Invalid RDS instance timeout format: 1h500s. Specify a duration using 'h' and 'm' only. E.g. 2h30m",
        ),
        (
            {"unknown_key": "55m"},
            "Timeouts must be a dictionary with 'create', 'update' and/or 'delete' keys. Offending keys: {'unknown_key'}.",
        ),
        (
            "Not_A_Dictionary",
            "Timeouts must be a dictionary with 'create', 'update' and/or 'delete' keys.",
        ),
    ],
)
def test_validate_timeouts_nok(timeouts: Any, expected_value_error: str) -> None:
    factory = AWSRdsFactory(er_inventory=Mock(), secret_reader=Mock())
    resource = ExternalResource(
        data={"timeouts": timeouts}, provision=Mock(spec=ExternalResourceProvision)
    )

    module_conf = ExternalResourceModuleConfiguration(reconcile_timeout_minutes=120)
    with pytest.raises(
        ValueError,
        match=rf".*{expected_value_error}.*",
    ):
        factory.validate(resource, module_conf)


def test_resolve_blue_green_deployment_parameter_group(
    factory: AWSRdsFactory,
    mocker: MockerFixture,
) -> None:
    rvr = mocker.patch(
        "reconcile.external_resources.aws.ResourceValueResolver", autospec=True
    )
    rvr.return_value.resolve.return_value = {
        "identifier": "test-rds",
        "blue_green_deployment": {
            "target": {
                "parameter_group": "/path/to/new_parameter_group",
            }
        },
    }
    rvr.return_value._get_values.return_value = {"k": "v"}
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test"},
        resource={
            "identifier": "test-rds",
            "provider": "rds",
            "blue_green_deployment": {
                "target": {
                    "parameter_group": "/path/to/new_parameter_group",
                }
            },
        },
        namespace={},
    )
    module_conf = ExternalResourceModuleConfiguration()

    result = factory.resolve(spec, module_conf)

    assert result == {
        "identifier": "test-rds",
        "blue_green_deployment": {
            "target": {
                "parameter_group": {"k": "v"},
            },
        },
        "output_prefix": "test-rds-rds",
        "timeouts": DEFAULT_EXPECTED_TIMEOUTS,
    }


def test_resolve_replica_source(
    factory: AWSRdsFactory,
    mocker: MockerFixture,
) -> None:
    rvr = mocker.patch(
        "reconcile.external_resources.aws.ResourceValueResolver", autospec=True
    )
    rvr_1 = create_autospec(ResourceValueResolver)
    rvr_2 = create_autospec(ResourceValueResolver)
    rvr.side_effect = [
        rvr_1,
        rvr_2,
    ]
    rvr_1.resolve.return_value = {
        "identifier": "test-rds-read-replica",
        "replica_source": "test-rds",
    }
    rvr_2.resolve.return_value = {
        "identifier": "test-rds",
        "region": "us-east-1",
        "blue_green_deployment": {
            "enabled": True,
            "target": {
                "parameter_group": "/path/to/new_parameter_group",
            },
        },
    }
    rvr_2._get_values.return_value = {"k": "v"}
    spec = ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test"},
        resource={
            "identifier": "test-rds-read-replica",
            "provider": "rds",
        },
        namespace={},
    )
    module_conf = ExternalResourceModuleConfiguration()

    result = factory.resolve(spec, module_conf)

    assert result == {
        "identifier": "test-rds-read-replica",
        "replica_source": {
            "identifier": "test-rds",
            "region": "us-east-1",
            "blue_green_deployment": {
                "enabled": True,
                "target": {
                    "parameter_group": {"k": "v"},
                },
            },
        },
        "output_prefix": "test-rds-read-replica-rds",
        "timeouts": DEFAULT_EXPECTED_TIMEOUTS,
    }
