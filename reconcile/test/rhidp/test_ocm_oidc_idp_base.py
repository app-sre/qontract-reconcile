from collections.abc import Sequence
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.rhidp.common import (
    Cluster,
    StatusValue,
)
from reconcile.rhidp.ocm_oidc_idp.base import (
    IDPState,
    act,
    fetch_current_state,
    fetch_desired_state,
)
from reconcile.utils.ocm.base import (
    OCMOIdentityProvider,
    OCMOIdentityProviderGithub,
    OCMOIdentityProviderOidc,
    OCMOIdentityProviderOidcOpenId,
)
from reconcile.utils.ocm_base_client import OCMBaseClient

IDP_OIDC = OCMOIdentityProviderOidc(
    name="oidc-auth",
    open_id=OCMOIdentityProviderOidcOpenId(
        client_id="client-id-cluster-1",
        issuer="https://issuer.com",
    ),
)
IDP_GH = OCMOIdentityProviderGithub(id="idp-2", name="gh-auth")
IDP_OTHER = OCMOIdentityProvider(id="idp-3", name="other-auth", type="other")


@pytest.fixture
def get_identity_providers_mock(mocker: MockerFixture) -> Mock:
    m = mocker.patch(
        "reconcile.rhidp.ocm_oidc_idp.base.get_identity_providers", autospec=True
    )
    m.return_value = iter([IDP_OIDC, IDP_GH])
    return m


def test_ocm_oidc_idp_fetch_current_state(
    ocm_base_client: OCMBaseClient,
    get_identity_providers_mock: Mock,
    clusters: Sequence[Cluster],
) -> None:
    current_state = fetch_current_state(ocm_base_client, [clusters[0]])
    assert current_state == [
        IDPState(
            cluster=clusters[0],
            idp=IDP_OIDC,
        ),
        IDPState(
            cluster=clusters[0],
            idp=IDP_GH,
        ),
    ]


def test_ocm_oidc_idp_fetch_desired_state(
    secret_reader: Mock, clusters: Sequence[Cluster]
) -> None:
    idp = OCMOIdentityProviderOidc(
        name="oidc-auth",
        open_id=OCMOIdentityProviderOidcOpenId(
            client_id="client_id",
            client_secret="client_secret",
            issuer="https://issuer.com",
        ),
    )
    secret_reader.read_all_secret.return_value = {
        "client_id": "client_id",
        "client_id_issued_at": 0,
        "client_name": "client_name",
        "client_secret": "client_secret",
        "client_secret_expires_at": 0,
        "grant_types": ["just-garbage"],
        "redirect_uris": ["just-garbage"],
        "registration_access_token": "just-garbage",
        "registration_client_uri": "just-garbage",
        "request_uris": ["just-garbage"],
        "response_types": ["just-garbage"],
        "subject_type": "just-garbage",
        "tls_client_certificate_bound_access_tokens": False,
        "token_endpoint_auth_method": "just-garbage",
        "issuer": "https://issuer.com",
    }
    desired_state = fetch_desired_state(
        secret_reader, clusters, vault_input_path="foo/bar"
    )
    assert desired_state == [
        IDPState(
            cluster=clusters[0],
            idp=idp,
        ),
        IDPState(
            cluster=clusters[1],
            idp=idp,
        ),
    ]


@pytest.mark.parametrize("dry_run", [True, False])
def test_ocm_oidc_idp_act(
    mocker: MockerFixture,
    ocm_base_client: OCMBaseClient,
    clusters: Sequence[Cluster],
    dry_run: bool,
) -> None:
    MANAGED_OIDC_NAME = "oidc-auth"
    cluster_auth_enabled = clusters[0]
    cluster_auth_disabled = clusters[1]
    cluster_auth_disabled.auth.status = StatusValue.DISABLED.value
    cluster_auth_enforced = clusters[2]
    cluster_auth_enforced.auth.status = StatusValue.ENFORCED.value

    idp = OCMOIdentityProviderOidc(
        name=MANAGED_OIDC_NAME,
        open_id=OCMOIdentityProviderOidcOpenId(
            client_id="client_id",
            client_secret="client_secret",
            issuer="https://issuer.com",
        ),
    )
    idp_update = idp.copy(deep=True)
    idp_update.open_id.client_id = "other-client-id"
    gh_idp = OCMOIdentityProviderGithub(id="idp-2", name="gh-auth")

    idp_in_sync = IDPState(cluster=cluster_auth_enabled, idp=idp)
    idp_to_be_ignored = IDPState(cluster=cluster_auth_enabled, idp=gh_idp)
    idp_to_be_changed = IDPState(cluster=cluster_auth_enabled, idp=idp_update)
    idp_to_be_removed = IDPState(cluster=cluster_auth_disabled, idp=idp)
    idp_to_be_added = IDPState(cluster=cluster_auth_enforced, idp=idp)
    gh_idp_to_be_removed = IDPState(cluster=cluster_auth_enforced, idp=gh_idp)

    current_state = [
        idp_in_sync,
        idp_to_be_removed,
        idp_to_be_ignored,
        gh_idp_to_be_removed,
    ]
    desired_state = [idp_in_sync, idp_to_be_added, idp_to_be_changed]

    add_identity_provider_mock = mocker.patch(
        "reconcile.rhidp.ocm_oidc_idp.base.add_identity_provider",
        autospec=True,
    )
    update_identity_provider_mock = mocker.patch(
        "reconcile.rhidp.ocm_oidc_idp.base.update_identity_provider",
        autospec=True,
    )
    delete_identity_provider_mock = mocker.patch(
        "reconcile.rhidp.ocm_oidc_idp.base.delete_identity_provider",
        autospec=True,
    )
    act(
        dry_run=dry_run,
        ocm_api=ocm_base_client,
        current_state=current_state,
        desired_state=desired_state,
        managed_idps=[MANAGED_OIDC_NAME],
    )
    if dry_run:
        add_identity_provider_mock.assert_not_called()
        update_identity_provider_mock.assert_not_called()
        delete_identity_provider_mock.assert_not_called()
        return

    # non dry-run
    add_identity_provider_mock.assert_called_once_with(
        ocm_base_client,
        idp_to_be_added.cluster.ocm_cluster,
        idp_to_be_added.idp,
    )
    delete_identity_provider_mock.assert_any_call(
        ocm_base_client, idp_to_be_removed.idp
    )
    delete_identity_provider_mock.assert_any_call(
        ocm_base_client, gh_idp_to_be_removed.idp
    )
    update_identity_provider_mock.assert_called_once_with(
        ocm_base_client, idp_to_be_changed.idp
    )
