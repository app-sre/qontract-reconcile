from collections.abc import Callable, Sequence
from typing import (
    Any,
    Protocol,
    TypeVar,
)

from pydantic import (
    BaseModel,
    Extra,
)

from reconcile.gql_definitions.fragments.membership_source import (
    MembershipProviderSourceV1,
    RoleMembershipSource,
)


class User(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def org_username(self) -> str: ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class Bot(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def org_username(self) -> str | None: ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class RoleWithMemberships(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def users(self) -> Sequence[User]: ...

    @property
    def bots(self) -> Sequence[Bot]: ...

    @property
    def member_sources(self) -> Sequence[RoleMembershipSource] | None: ...


class RoleUser(BaseModel):
    name: str
    org_username: str
    github_username: str | None
    quay_username: str | None
    slack_username: str | None
    pagerduty_username: str | None
    aws_username: str | None
    cloudflare_user: str | None
    public_gpg_key: str | None
    tag_on_cluster_updates: bool | None = False
    tag_on_merge_requests: bool | None = False

    class Config:
        extra = Extra.ignore


class RoleBot(BaseModel):
    name: str
    description: str | None
    org_username: str | None
    github_username: str | None
    gitlab_username: str | None
    openshift_serviceaccount: str | None
    quay_username: str | None

    class Config:
        extra = Extra.ignore


RoleMember = RoleUser | RoleBot

ProviderGroup = tuple[str, str]

ProviderSource = TypeVar("ProviderSource", bound=MembershipProviderSourceV1)

ProviderResolver = Callable[
    [str, ProviderSource, set[str]], dict[ProviderGroup, list[RoleMember]]
]
