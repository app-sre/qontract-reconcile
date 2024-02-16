from typing import Optional

from pydantic import BaseModel, Field

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret

"""
These models reflect an app-interface ROSA cluster including its
- spec details
- account details
- ocm details

without any Optionals

This allows for easier handling with AppInterface ROSA cluster assets because
there is no need to constantly check for None values.
"""


class AWSAccount(BaseModel):
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")
    automation_token: VaultSecret = Field(..., alias="automationToken")


class ROSAClusterSpec(BaseModel):
    q_id: Optional[str] = Field(..., alias="id")
    product: str = Field(..., alias="product")
    channel: str = Field(..., alias="channel")
    region: str = Field(..., alias="region")
    account: AWSAccount = Field(..., alias="account")


class OCMEnvironment(BaseModel):
    url: str = Field(..., alias="url")
    access_token_client_id: str = Field(..., alias="accessTokenClientId")
    access_token_url: str = Field(..., alias="accessTokenUrl")
    access_token_client_secret: VaultSecret = Field(
        ..., alias="accessTokenClientSecret"
    )


class OCMOrganization(BaseModel):
    environment: OCMEnvironment = Field(..., alias="environment")
    org_id: str = Field(..., alias="orgId")
    access_token_client_id: Optional[str] = Field(..., alias="accessTokenClientId")
    access_token_url: Optional[str] = Field(..., alias="accessTokenUrl")
    access_token_client_secret: Optional[VaultSecret] = Field(
        ..., alias="accessTokenClientSecret"
    )


class ROSACluster(BaseModel):
    name: str = Field(..., alias="name")
    spec: ROSAClusterSpec = Field(..., alias="spec")
    ocm: OCMOrganization = Field(..., alias="ocm")
