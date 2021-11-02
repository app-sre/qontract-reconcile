from unittest.mock import create_autospec

import pytest

import reconcile.dyn_traffic_director as integ


@pytest.fixture
def zones_nodes_fixture(mocker):
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


def test_get_node(zones_nodes_fixture):
    res = integ.get_node('zoneA-nodeA.')
    assert isinstance(res, integ.dyn_zones.Node)
    assert res.fqdn == 'zoneA-nodeA.'


def test_get_node_not_found(zones_nodes_fixture):
    res = integ.get_node('non-existing-node')
    assert res is None
