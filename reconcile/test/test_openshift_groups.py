from reconcile import openshift_groups as og


def test_get_state_count_combinations():
    state = [
        {"cluster": "c1"},
        {"cluster": "c2"},
        {"cluster": "c1"},
        {"cluster": "c3"},
        {"cluster": "c2"},
    ]
    expected = {"c1": 2, "c2": 2, "c3": 1}
    assert expected == og.get_state_count_combinations(state)
