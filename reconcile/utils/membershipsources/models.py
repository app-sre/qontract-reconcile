from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import (
    Any,
    Protocol,
    TypeVar,
)

from pydantic import (
    BaseModel,
)


class MembershipProviderSource(Protocol):
    """Structural shape of a membership provider's `source` variant.

    `provider` is the discriminator string (e.g. "app-interface", "ldap"),
    matching the GraphQL interface's own `interfaceResolve.field: provider`.
    Dispatch keys on this string, never on the concrete Python type - this
    is what lets the resolver framework stay independent of any concrete
    class from reconcile/gql_definitions.
    """

    @property
    def provider(self) -> str: ...


class MembershipProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def has_audit_trail(self) -> bool: ...

    @property
    def source(self) -> MembershipProviderSource: ...


class MembershipSourceEntry(Protocol):
    @property
    def group(self) -> str: ...

    @property
    def provider(self) -> MembershipProvider: ...


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
    def member_sources(self) -> Sequence[MembershipSourceEntry] | None: ...


class ProviderMember(Protocol):
    """Structural shape every provider-resolved member must satisfy.

    org_username is what resolve_role() dedups on; model_dump is what lets
    the framework convert a raw provider result (e.g. an LDAP group member,
    or a remote app-interface UserV1/BotV1) into the caller-supplied
    user_cls, so a provider never needs to know about any integration's
    user attributes. User and Bot both satisfy this structurally too.
    """

    @property
    def org_username(self) -> str | None: ...

    def model_dump(self, *, by_alias: bool = False) -> dict[str, Any]: ...


ProviderGroup = tuple[str, str]

ProviderSource = TypeVar("ProviderSource", bound=MembershipProviderSource)

ProviderResolver = Callable[
    [str, ProviderSource, set[str]], dict[ProviderGroup, list[ProviderMember]]
]

# Async counterpart of ProviderResolver, used by async_resolver.resolve_role_members.
AsyncProviderResolver = Callable[
    [str, ProviderSource, set[str]],
    Coroutine[Any, Any, dict[ProviderGroup, list[ProviderMember]]],
]


def resolve_role[U: BaseModel](
    role: RoleWithMemberships,
    user_cls: type[U],
    resolved_groups: Mapping[ProviderGroup, list[ProviderMember]],
) -> list[U]:
    """Merge a role's explicit users/bots with memberSources-resolved members.

    Shared by both the sync and async resolvers - only how resolved_groups
    gets built differs between them. Converts every member to user_cls via
    user_cls(**member.model_dump()) and deduplicates by org_username:
    explicit users/bots are added first and win over a memberSources-resolved
    member sharing the same org_username, since they carry richer,
    integration-specific data.

    user_cls itself is not required to declare org_username as a type-checked
    field (it is caller-supplied and free-form), so the dedup key is read
    back off the constructed instance defensively via getattr.
    """
    seen: set[str] = set()
    members: list[U] = []

    def add(source: ProviderMember) -> None:
        member = user_cls(**source.model_dump())
        org_username: str | None = getattr(member, "org_username", None)
        if org_username and org_username not in seen:
            seen.add(org_username)
            members.append(member)

    for user in role.users or []:
        add(user)
    for bot in role.bots or []:
        if bot.org_username:
            add(bot)

    for member_source in role.member_sources or []:
        key = (member_source.provider.name, member_source.group)
        for provider_member in resolved_groups.get(key, []):
            add(provider_member)

    return members
