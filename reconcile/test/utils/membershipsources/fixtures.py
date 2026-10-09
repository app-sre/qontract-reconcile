from pydantic import BaseModel, Field

from reconcile.gql_definitions.fragments.membership_source import (
    MembershipProviderSourceV1,
    MembershipProviderV1,
    RoleMembershipSource,
)


class MockUser(BaseModel):
    name: str
    org_username: str
    github_username: str


class MockBot(BaseModel):
    name: str
    org_username: str | None = None


class MockRole(BaseModel):
    name: str
    users: list[MockUser]
    bots: list[MockBot]
    member_sources: list[RoleMembershipSource] | None = None


class MockGithubUser(BaseModel, frozen=True):
    org_username: str
    github_username: str | None = None


class CustomRole[U: BaseModel](BaseModel, frozen=True):
    """Test-owned role for exercising custom membership identity models."""

    name: str
    users: list[U]
    bots: list[MockBot] = Field(default_factory=list)
    member_sources: list[RoleMembershipSource] | None = Field(
        None, alias="memberSources"
    )


def build_role(
    name: str,
    users: list[str] | None = None,
    bots: list[str] | None = None,
    member_sources: list[RoleMembershipSource] | None = None,
) -> MockRole:
    return MockRole(
        name=name,
        users=[
            MockUser(name=u, org_username=u, github_username=u) for u in users or []
        ],
        bots=[MockBot(name=b, org_username=b) for b in bots or []],
        member_sources=member_sources,
    )


def build_app_interface_membership_source(
    name: str,
    group: str,
    source: MembershipProviderSourceV1,
    has_audit_trail: bool = True,
) -> RoleMembershipSource:
    return RoleMembershipSource(
        provider=MembershipProviderV1(
            name=name,
            hasAuditTrail=has_audit_trail,
            source=source,
        ),
        group=group,
    )


def build_ldap_membership_source(
    name: str,
    group: str,
    has_audit_trail: bool = False,
) -> RoleMembershipSource:
    return RoleMembershipSource(
        provider=MembershipProviderV1(
            name=name,
            hasAuditTrail=has_audit_trail,
            source=MembershipProviderSourceV1(provider="ldap"),
        ),
        group=group,
    )
