from unittest.mock import create_autospec

import pytest

import reconcile.dyn_traffic_director as integ


@pytest.fixture
def get_all_zones_fixture(mocker):
    mock_get_all_zones = mocker.patch.object(
        integ.dyn_zones, "get_all_zones", autospec=True
    )

    zone_a = create_autospec(integ.dyn_zones.Zone)
    zone_a.get_all_nodes.return_value = [
        integ.dyn_zones.Node("zoneA-nodeA"),
        integ.dyn_zones.Node("zoneA-nodeB"),
    ]

    zone_b = create_autospec(integ.dyn_zones.Zone)
    zone_b.get_all_nodes.return_value = [
        integ.dyn_zones.Node("zoneB-nodeA"),
        integ.dyn_zones.Node("zoneB-nodeB"),
    ]

    mock_get_all_zones.return_value = [zone_a, zone_b]


def test__get_dyn_node(get_all_zones_fixture):
    res = integ._get_dyn_node("zoneA-nodeA.")
    assert isinstance(res, integ.dyn_zones.Node)
    assert res.fqdn == "zoneA-nodeA."


def test__get_dyn_node_not_found(get_all_zones_fixture):
    with pytest.raises(integ.DynResourceNotFound):
        integ._get_dyn_node("non-existing-node")


def test__new_dyn_cname_record():
    rec = integ._new_dyn_cname_record("somerecord")
    assert isinstance(rec, integ.DSFCNAMERecord)
    assert rec.cname == "somerecord"
    assert rec.weight == 100


def test__new_dyn_cname_record_with_weight():
    rec = integ._new_dyn_cname_record("somerecord", weight=50)
    assert isinstance(rec, integ.DSFCNAMERecord)
    assert rec.cname == "somerecord"
    assert rec.weight == 50


def generate_state(td_count: int, node_count: int, records_count: int, ttl: int):
    """Utility method to generate a state dict"""
    return {
        f"td{i}.example.com": {
            "name": f"td{i}.example.com",
            "nodes": [f"node{n}" for n in range(node_count)],
            "records": [
                {"hostname": f"rec{r}", "weight": 100} for r in range(records_count)
            ],
            "ttl": ttl,
        }
        for i in range(td_count)
    }


def test_process_tds_empty_state(mocker):
    """Tests that nothing happens given empty states"""
    current = generate_state(0, 0, 0, 0)
    desired = generate_state(0, 0, 0, 0)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_not_called()


def test_process_tds_noop(mocker):
    """Tests that nothing happens given identical current & desired inputs"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(1, 1, 3, 30)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_not_called()


def test_process_tds_added_td(mocker):
    """Tests that TDs are added given an additional TD in desired state"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(2, 1, 3, 30)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_called_once()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_not_called()


def test_process_tds_deleted_td(mocker):
    """Tests that TD is deleted given it is missing from the desired state"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(0, 1, 3, 30)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_called_once()
    mock_update_td.assert_not_called()


def test_process_tds_updated_td_nodes(mocker):
    """Tests that TDs are updated given a change in node count in desired
    state"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(1, 2, 3, 30)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_called_once()


def test_process_tds_updated_td_ttl(mocker):
    """Tests that TDs are updated given a change in ttl in desired state"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(1, 1, 3, 300)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_called_once()


def test_process_tds_updated_td_records(mocker):
    """Tests that TDs are updated given a change in records count in desired
    state"""
    current = generate_state(1, 1, 3, 30)
    desired = generate_state(1, 1, 4, 30)

    mock_create_td = mocker.patch.object(integ, "create_td", autospec=True)
    mock_delete_td = mocker.patch.object(integ, "delete_td", autospec=True)
    mock_update_td = mocker.patch.object(integ, "update_td", autospec=True)

    integ.process_tds(current, desired, dry_run=True, enable_deletion=False)

    mock_create_td.assert_not_called()
    mock_delete_td.assert_not_called()
    mock_update_td.assert_called_once()
