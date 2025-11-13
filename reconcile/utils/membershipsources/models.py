from collections.abc import Callable, Sequence
from typing import (
    Any,
    Protocol,
    TypeVar,
)

from pydantic import (
    BaseModel,
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

    def model_dump(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class Bot(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def org_username(self) -> str | None: ...

    def model_dump(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class RoleWithMemberships(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def users(self) -> Sequence[User]: ...

    @property
    def bots(self) -> Sequence[Bot]: ...

    @property
    def member_sources(self) -> Sequence[RoleMembershipSource] | None: ...


class RoleUser(BaseModel, extra="ignore"):
    name: str
    org_username: str
    github_username: str | None = None
    quay_username: str | None = None
    pagerduty_username: str | None = None
    aws_username: str | None = None
    cloudflare_user: str | None = None
    public_gpg_key: str | None = None
    tag_on_cluster_updates: bool | None = False
    tag_on_merge_requests: bool | None = False


class RoleBot(BaseModel, extra="ignore"):
    name: str
    description: str | None = None
    org_username: str | None = None
    github_username: str | None = None
    gitlab_username: str | None = None
    openshift_serviceaccount: str | None = None
    quay_username: str | None = None


RoleMember = RoleUser | RoleBot

ProviderGroup = tuple[str, str]

ProviderSource = TypeVar("ProviderSource", bound=MembershipProviderSourceV1)

ProviderResolver = Callable[
    [str, ProviderSource, set[str]], dict[ProviderGroup, list[RoleMember]]
]
