import pytest

from reconcile.email_sender import collect_to
from reconcile.gql_definitions.email_sender.emails import AppInterfaceEmailV1, OwnerV1
from reconcile.gql_definitions.fragments.email_service import EmailServiceOwners
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


def test_email_sender_collect_to(emails: list[AppInterfaceEmailV1]) -> None:
    for email in emails:
        match email.name:
            case "all-service-owners":
                assert collect_to(
                    email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
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
            case "all-users":
                assert collect_to(
                    email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
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
            case "no-aliases":
                assert collect_to(
                    email.q_to, all_users=ALL_USERS, all_services=ALL_APPS
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
            case "namespaces":
                with pytest.raises(NotImplementedError):
                    collect_to(email.q_to, all_users=ALL_USERS, all_services=ALL_APPS)
            case "clusters":
                with pytest.raises(NotImplementedError):
                    collect_to(email.q_to, all_users=ALL_USERS, all_services=ALL_APPS)
            case _:
                raise ValueError(f"Unknown email name: {email.name}")
