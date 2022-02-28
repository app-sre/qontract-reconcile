def get_dedicated_admin_groups():
    return ["dedicated-admins", "system:serviceaccounts:dedicated-admin"]


def get_expected_roles():
    return [
        "admin",
        "dedicated-project-admin",
        "dedicated-admins-project",
        "ClusterRole/admin",
        "ClusterRole/dedicated-admins-project",
    ]


def get_expected_rolebindings():
    groups = get_dedicated_admin_groups()
    expected_rolebindings = [
        {"name": "admin-0", "role": "admin", "groups": groups},
        {
            "name": "dedicated-project-admin",
            "role": "dedicated-project-admin",
            "groups": groups,
        },
    ]

    return expected_rolebindings


def test_project_admin_rolebindings(oc, project):
    rolebindings = oc.get(project, "RoleBinding")["items"]
    project_rbs = [
        rb
        for rb in rolebindings
        if rb.get("groupNames") == get_dedicated_admin_groups()
        or rb["roleRef"]["name"] in get_expected_roles()
    ]
    roles = {rb["roleRef"]["name"] for rb in project_rbs}
    assert len(roles) == 2
    assert "admin" in roles
