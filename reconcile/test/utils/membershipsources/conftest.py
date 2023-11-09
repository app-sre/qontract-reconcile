import pytest

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


@pytest.fixture
def app_interface_membership_provider() -> AppInterfaceMembershipProviderSourceV1:
    return AppInterfaceMembershipProviderSourceV1(
        url="url",
        username=VaultSecret(
            path="path",
            field="username",
            format="format",
            version=1,
        ),
        password=VaultSecret(
            path="path",
            field="password",
            format="format",
            version=1,
        ),
    )
