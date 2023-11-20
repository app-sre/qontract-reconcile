from typing import Optional

from pydantic import BaseModel

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
    org_username: Optional[str]


class MockRole(BaseModel):
    name: str
    users: list[MockUser]
    bots: list[MockBot]
    member_sources: Optional[list[RoleMembershipSource]]


def build_role(
    name: str,
    users: Optional[list[str]] = None,
    bots: Optional[list[str]] = None,
    member_sources: Optional[list[RoleMembershipSource]] = None,
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
