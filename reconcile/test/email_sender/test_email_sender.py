import pytest

from reconcile.email_sender import collect_to
from reconcile.gql_definitions.email_sender.emails import AppInterfaceEmailV1
from reconcile.gql_definitions.fragments.email_service import (
    EmailServiceOwners,
    OwnerV1,
)
from reconcile.gql_definitions.fragments.email_user import EmailUser

ALL_APPS = [
    EmailServiceOwners(
        serviceOwners=[
            OwnerV1(email="all-apps-app1-email-1"),
            OwnerV1(email="all-apps-app1-email-1"),
        ]
    ),
    EmailServiceOwners(
        serviceOwners=[
            OwnerV1(email="all-apps-app2-email-1"),
            OwnerV1(email="all-apps-app2-email-1"),
        ]
    ),
]

ALL_USERS = [
    EmailUser(org_username="all-users-user-1"),
    EmailUser(org_username="all-users-user-2"),
    EmailUser(org_username="no-duplicates-please"),
]


def test_email_sender_collect_to_all_service_owners_email(
    all_service_owners_email: AppInterfaceEmailV1,
) -> None:
    assert collect_to(
        all_service_owners_email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
    ) == {
        "account1-email1",
        "account1-email2",
        "account2-email1",
        "account2-email2",
        "all-apps-app1-email-1",
        "all-apps-app2-email-1",
        "no-duplicates-please",
        "role1-username1",
        "role1-username2",
        "role2-username1",
        "role2-username2",
        "username1",
        "username2",
    }


def test_email_sender_collect_to_all_users_email(
    all_users_email: AppInterfaceEmailV1,
) -> None:
    assert collect_to(
        all_users_email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
    ) == {
        "account1-email1",
        "account1-email2",
        "account2-email1",
        "account2-email2",
        "all-users-user-1",
        "all-users-user-2",
        "name2@example.com",
        "name@example.com",
        "no-duplicates-please",
        "role1-username1",
        "role1-username2",
        "role2-username1",
        "role2-username2",
    }


def test_email_sender_collect_to_no_aliases_email(
    no_aliases_email: AppInterfaceEmailV1,
) -> None:
    assert collect_to(
        no_aliases_email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
    ) == {
        "account1-email1",
        "account1-email2",
        "account2-email1",
        "account2-email2",
        "name2@example.com",
        "name@example.com",
        "role1-username1",
        "role1-username2",
        "role2-username1",
        "role2-username2",
        "username1",
        "username2",
    }


def test_email_sender_collect_to_namespaces_email(
    namespaces_email: AppInterfaceEmailV1,
) -> None:
    with pytest.raises(NotImplementedError):
        collect_to(namespaces_email.q_to, all_users=ALL_USERS, all_services=ALL_APPS)


def test_email_sender_collect_to_clusters_email(
    clusters_email: AppInterfaceEmailV1,
) -> None:
    with pytest.raises(NotImplementedError):
        collect_to(clusters_email.q_to, all_users=ALL_USERS, all_services=ALL_APPS)
