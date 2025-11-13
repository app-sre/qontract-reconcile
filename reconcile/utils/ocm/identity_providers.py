from collections.abc import Generator

from reconcile.utils.ocm.base import (
    OCMCluster,
    OCMOIdentityProvider,
    OCMOIdentityProviderGithub,
    OCMOIdentityProviderOidc,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_identity_providers(
    ocm_api: OCMBaseClient, ocm_cluster: OCMCluster
) -> Generator[
    OCMOIdentityProvider | OCMOIdentityProviderOidc | OCMOIdentityProviderGithub,
    None,
    None,
]:
    """Get all identity providers."""
    if ocm_cluster.identity_providers.href:
        for idp_dict in ocm_api.get_paginated(
            api_path=ocm_cluster.identity_providers.href
        ):
            match idp_dict["type"]:
                case "OpenIDIdentityProvider":
                    yield OCMOIdentityProviderOidc(**idp_dict)
                case "GithubIdentityProvider":
                    yield OCMOIdentityProviderGithub(**idp_dict)
                case _:
                    yield OCMOIdentityProvider(**idp_dict)


def add_identity_provider(
    ocm_api: OCMBaseClient,
    ocm_cluster: OCMCluster,
    idp: OCMOIdentityProviderOidc,  # no other IDP types are tested and supported yet
) -> None:
    """Creates a new identity provider."""
    if not ocm_cluster.identity_providers.href:
        raise ValueError(
            f"Cluster {ocm_cluster.name} does not support identity providers."
        )
    ocm_api.post(
        api_path=ocm_cluster.identity_providers.href,
        data=idp.dict(by_alias=True, exclude_none=True),
    )


def update_identity_provider(
    ocm_api: OCMBaseClient,
    idp: OCMOIdentityProviderOidc,  # no other IDP types are tested and supported yet
) -> None:
    """Creates a new identity provider."""
    if not idp.href:
        raise ValueError(f"IDP {idp.name} does not have a href!")
    ocm_api.patch(
        api_path=idp.href,
        data=idp.dict(by_alias=True, exclude_none=True, exclude={"name"}),
    )


def delete_identity_provider(ocm_api: OCMBaseClient, idp: OCMOIdentityProvider) -> None:
    """Delete a identity provider."""
    if not idp.href:
        raise ValueError(f"IDP {idp.name} does not have a href!")
    ocm_api.delete(api_path=idp.href)
