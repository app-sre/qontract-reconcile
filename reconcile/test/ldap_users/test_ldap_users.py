from reconcile import ldap_users
from reconcile.gql_definitions.common.users_paths import UserV1


def test_transform_users_paths(raw_users_paths: list[UserV1]) -> None:
    users = ldap_users.transform_users_paths(raw_users_paths)

    assert len(users) == 3
    for user in users:
        assert isinstance(user, ldap_users.UserPaths)
        assert len(user.paths) == 5
        for path in user.paths:
            assert isinstance(path, ldap_users.PathSpec)


def test_filter_users_not_exists(users_paths: list[ldap_users.UserPaths]) -> None:
    users = ldap_users.filter_users_not_exists(users_paths, {"username1", "username2"})

    assert len(users) == 1
    assert users[0].username == "username3"


def test_get_usernames(users_paths: list[ldap_users.UserPaths]) -> None:
    usernames = ldap_users.get_usernames(users_paths)

    assert usernames == ["username1", "username2", "username3"]
