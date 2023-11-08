from collections.abc import Sequence
from typing import (
    Any,
    Callable,
    Optional,
    Protocol,
    TypeVar,
    Union,
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
    def name(self) -> str:
        ...

    @property
    def org_username(self) -> str:
        ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]:
        ...


class Bot(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def org_username(self) -> Optional[str]:
        ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]:
        ...


class RoleWithMemberships(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def users(self) -> Sequence[User]:
        ...

    @property
    def bots(self) -> Sequence[Bot]:
        ...

    @property
    def member_sources(self) -> Optional[Sequence[RoleMembershipSource]]:
        ...


class RoleUser(BaseModel):
    name: str
    org_username: str
    github_username: Optional[str]
    quay_username: Optional[str]
    slack_username: Optional[str]
    pagerduty_username: Optional[str]
    aws_username: Optional[str]
    cloudflare_user: Optional[str]
    public_gpg_key: Optional[str]
    tag_on_cluster_updates: Optional[bool] = False
    tag_on_merge_requests: Optional[bool] = False

    class Config:
        extra = Extra.ignore


class RoleBot(BaseModel):
    name: str
    description: Optional[str]
    org_username: Optional[str]
    github_username: Optional[str]
    gitlab_username: Optional[str]
    openshift_serviceaccount: Optional[str]
    quay_username: Optional[str]

    class Config:
        extra = Extra.ignore


RoleMember = Union[RoleUser, RoleBot]

ProviderGroup = tuple[str, str]

ProviderSource = TypeVar("ProviderSource", bound=MembershipProviderSourceV1)

ProviderResolver = Callable[
    [str, ProviderSource, set[str]], dict[ProviderGroup, list[RoleMember]]
]
