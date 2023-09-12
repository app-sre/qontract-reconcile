from datetime import (
    date,
    timedelta,
)

import pytest
from pytest_mock import MockerFixture

import reconcile.gabi_authorized_users as gabi_u
import reconcile.openshift_base as ob
from reconcile.test.fixtures import Fixtures
from reconcile.utils.aggregated_list import RunnerException
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory

fixture = Fixtures("gabi_authorized_users").get_anymarkup("api.yml")


def test_gabi_authorized_users_apply(mocker: MockerFixture) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("server", "gabi-db", "ConfigMap")
    gabi_instance = fixture["gql_response"][0]
    gabi_u.fetch_desired_state([gabi_instance], ri)
    mock_apply = mocker.patch.object(ob, "apply", autospec=True)
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    ob.realize_data(True, oc_map, ri, 1)
    expected = OR(
        fixture["desired"],
        gabi_u.QONTRACT_INTEGRATION,
        gabi_u.QONTRACT_INTEGRATION_VERSION,
    )
    _, kwargs = mock_apply.call_args
    assert kwargs["resource"] == expected


def test_gabi_authorized_users_exist(mocker: MockerFixture) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type("server", "gabi-db", "ConfigMap")
    current = OR(
        fixture["current"],
        gabi_u.QONTRACT_INTEGRATION,
        gabi_u.QONTRACT_INTEGRATION_VERSION,
    )
    ri.add_current(
        "server",
        "gabi-db",
        "ConfigMap",
        current.name,
        current,
    )
    gabi_instance = fixture["gql_response"][0]
    gabi_u.fetch_desired_state([gabi_instance], ri)
    mock_apply = mocker.patch.object(ob, "apply", autospec=True)
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    ob.realize_data(True, oc_map, ri, 1)
    mock_apply.assert_not_called()


def test_gabi_authorized_users_exceed() -> None:
    expiration_date = date.today() + timedelta(days=(gabi_u.EXPIRATION_DAYS_MAX + 1))
    gabi_instance = fixture["gql_response"][0]
    gabi_instance["expirationDate"] = str(expiration_date)
    ri = ResourceInventory()
    with pytest.raises(RunnerException):
        gabi_u.fetch_desired_state([gabi_instance], ri)


def test_gabi_authorized_users_rds_not_found() -> None:
    gabi_instance = fixture["gql_response"][1]
    ri = ResourceInventory()
    with pytest.raises(RunnerException):
        gabi_u.fetch_desired_state([gabi_instance], ri)
