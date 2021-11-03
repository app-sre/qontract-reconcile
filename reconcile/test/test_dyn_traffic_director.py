from unittest.mock import create_autospec

import pytest

import reconcile.dyn_traffic_director as integ


@pytest.fixture
def get_all_zones_fixture(mocker):
    mock_get_all_zones = mocker.patch.object(
        integ.dyn_zones, 'get_all_zones', autospec=True)

    zone_a = create_autospec(integ.dyn_zones.Zone)
    zone_a.get_all_nodes.return_value = [
        integ.dyn_zones.Node('zoneA-nodeA'),
        integ.dyn_zones.Node('zoneA-nodeB'),
    ]

    zone_b = create_autospec(integ.dyn_zones.Zone)
    zone_b.get_all_nodes.return_value = [
        integ.dyn_zones.Node('zoneB-nodeA'),
        integ.dyn_zones.Node('zoneB-nodeB'),
    ]

    mock_get_all_zones.return_value = [zone_a, zone_b]


def test_get_node(get_all_zones_fixture):
    res = integ.get_node('zoneA-nodeA.')
    assert isinstance(res, integ.dyn_zones.Node)
    assert res.fqdn == 'zoneA-nodeA.'


def test_get_node_not_found(get_all_zones_fixture):
    res = integ.get_node('non-existing-node')
    assert res is None


# Mock Class for TrafficDirector
# The Dyn module's TrafficDirector class calls the Dyn API multiple times as
# part of it's constructor. This Mock class purpose is to avoid this and allow
# us to test our code without having to construct a fully valid TrafficDirector
class MockTrafficDirector(integ.dyn_services.TrafficDirector):
    def __init__(self, label):
        self._label = label
        self._service_id = label


@pytest.fixture
def get_all_dsf_services_fixture(mocker):
    mock_get_all_dsf_Services = mocker.patch.object(
        integ.dyn_services, 'get_all_dsf_services', autospec=True
    )

    mock_get_all_dsf_Services.return_value = [
        MockTrafficDirector('foo'),
        MockTrafficDirector('bar'),
        MockTrafficDirector('baz'),
    ]


def test_get_traffic_director_service(get_all_dsf_services_fixture):
    res = integ.get_traffic_director_service('bar')
    assert isinstance(res, integ.dyn_services.TrafficDirector)
    assert res.label == 'bar'
