def get_expected_rolebindings():
    groups = ['dedicated-admins', 'system:serviceaccounts:dedicated-admin']
    expected_rolebindings = [
        {'name': 'admin-0',
         'role': 'admin',
         'groups': groups},
        {'name': 'dedicated-project-admin',
         'role': 'dedicated-project-admin',
         'groups': groups},
    ]

    return expected_rolebindings