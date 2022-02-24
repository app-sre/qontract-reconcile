def get_expected_network_policy_names():
    return [
        "allow-from-default-namespace",
        "allow-from-ingress-namespace",
        "allow-from-same-namespace",
    ]


def test_project_network_policies(oc, project):
    network_policies = oc.get(project, "NetworkPolicy")["items"]
    project_nps = [
        np
        for np in network_policies
        if np["metadata"]["name"] in get_expected_network_policy_names()
    ]
    assert len(project_nps) == 2
    assert project_nps[0]["metadata"]["name"] != project_nps[1]["metadata"]["name"]
