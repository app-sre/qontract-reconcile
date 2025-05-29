from unittest.mock import call

from pytest_mock import MockType

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


def test_run(
    mocked_get_users_with_paths: MockType,
    mocked_get_ldap_settings: MockType,
    mocked_get_ldap_users: MockType,
    mocked_mr_client_gateway: MockType,
    mocked_create_delete_user_app_interface: MockType,
    mocked_create_delete_user_infra: MockType,
) -> None:
    app_interface_gitlab_project_id = "5"
    infra_gitlab_project_id = "3"
    ldap_users.run(False, app_interface_gitlab_project_id, infra_gitlab_project_id)

    assert mocked_mr_client_gateway.call_count == 2
    mocked_mr_client_gateway.assert_has_calls(
        [
            call(
                gitlab_project_id=app_interface_gitlab_project_id,
                sqs_or_gitlab="gitlab",
            ),
            call(gitlab_project_id=infra_gitlab_project_id, sqs_or_gitlab="gitlab"),
        ],
        any_order=True,
    )
    assert mocked_create_delete_user_app_interface.call_count == 2
    mocked_create_delete_user_app_interface.assert_has_calls(
        [
            call(
                "username2",
                [
                    PathSpec(type=PathTypes.USER, path="blah"),
                    PathSpec(type=PathTypes.REQUEST, path="test_path2"),
                    PathSpec(type=PathTypes.QUERY, path="another_test_path2"),
                    PathSpec(type=PathTypes.GABI, path="yet_another_test_path2"),
                    PathSpec(
                        type=PathTypes.SCHEDULE, path="and_yet_another_test_path2"
                    ),
                ],
            ),
            call(
                "username3",
                [
                    PathSpec(type=PathTypes.USER, path="blah"),
                    PathSpec(type=PathTypes.REQUEST, path="test_path3"),
                    PathSpec(type=PathTypes.QUERY, path="another_test_path3"),
                    PathSpec(type=PathTypes.GABI, path="yet_another_test_path3"),
                    PathSpec(
                        type=PathTypes.SCHEDULE, path="and_yet_another_test_path3"
                    ),
                ],
            ),
        ],
        any_order=True,
    )
    assert mocked_create_delete_user_app_interface.return_value.submit.call_count == 2
    mocked_create_delete_user_infra.assert_called_once_with(["username2", "username3"])
    mocked_create_delete_user_infra.return_value.submit.assert_called_once

