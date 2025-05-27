from reconcile import ldap_users
from reconcile.gql_definitions.common.users_with_paths import UserV1
from reconcile.utils.mr.user_maintenance import PathSpec, PathTypes


def test_transform_users_paths(users_with_paths: list[UserV1]) -> None:
    user_paths = ldap_users.transform_users_with_paths(users_with_paths)

    assert user_paths == [
        ldap_users.UserPaths(
            username="username1",
            paths=[
                PathSpec(type=PathTypes.USER, path="blah"),
                PathSpec(type=PathTypes.REQUEST, path="test_path1"),
                PathSpec(type=PathTypes.QUERY, path="another_test_path1"),
                PathSpec(type=PathTypes.GABI, path="yet_another_test_path1"),
                PathSpec(type=PathTypes.SCHEDULE, path="and_yet_another_test_path1"),
            ],
        ),
        ldap_users.UserPaths(
            username="username2",
            paths=[
                PathSpec(type=PathTypes.USER, path="blah"),
                PathSpec(type=PathTypes.REQUEST, path="test_path2"),
                PathSpec(type=PathTypes.QUERY, path="another_test_path2"),
                PathSpec(type=PathTypes.GABI, path="yet_another_test_path2"),
                PathSpec(type=PathTypes.SCHEDULE, path="and_yet_another_test_path2"),
            ],
        ),
        ldap_users.UserPaths(
            username="username3",
            paths=[
                PathSpec(type=PathTypes.USER, path="blah"),
                PathSpec(type=PathTypes.REQUEST, path="test_path3"),
                PathSpec(type=PathTypes.QUERY, path="another_test_path3"),
                PathSpec(type=PathTypes.GABI, path="yet_another_test_path3"),
                PathSpec(type=PathTypes.SCHEDULE, path="and_yet_another_test_path3"),
            ],
        ),
    ]


def test_filter_users_not_exists(users_paths: list[ldap_users.UserPaths]) -> None:
    users = ldap_users.filter_users_not_exists(users_paths, {"username1", "username2"})

    assert len(users) == 1
    assert users[0].username == "username3"


def test_get_usernames(users_paths: list[ldap_users.UserPaths]) -> None:
    usernames = ldap_users.get_usernames(users_paths)

    assert usernames == ["username1", "username2", "username3"]
