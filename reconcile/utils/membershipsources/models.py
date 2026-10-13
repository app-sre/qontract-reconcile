from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import (
    Any,
    Protocol,
    Self,
    TypeVar,
    get_args,
    overload,
    runtime_checkable,
)

from pydantic import (
    BaseModel,
    ValidationError,
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
    def org_username(self) -> str: ...

    def model_dump(self, *, by_alias: bool = False) -> dict[str, Any]: ...


@runtime_checkable
class RoleMembershipFields(Protocol):
    """Shared membership fields, including queries that do not select bots."""

    @property
    def name(self) -> str: ...

    @property
    def users(self) -> Sequence[User]: ...

    @property
    def member_sources(self) -> Sequence[MembershipSourceEntry] | None: ...

    def model_dump(
        self, *, by_alias: bool = False, round_trip: bool = False
    ) -> dict[str, Any]: ...

    @classmethod
    def model_validate(cls, obj: Any) -> Self: ...


@runtime_checkable
class RoleWithMemberships(RoleMembershipFields, Protocol):
    """A role that also exposes an optional collection of generated bot models."""

    @property
    def bots(self) -> Sequence[BaseModel] | None: ...


@runtime_checkable
class GithubIdentity(Protocol):
    """Structural GitHub identity, which can be absent on provider users."""

    @property
    def github_username(self) -> str | None: ...


def has_ldap_sources(roles: Sequence[RoleMembershipFields]) -> bool:
    """Whether the selected roles need LDAP connectivity."""
    return any(
        source.provider.source.provider == "ldap"
        for role in roles
        for source in role.member_sources or []
    )


class ProviderMember(Protocol):
    """Structural shape every provider-resolved member must satisfy.

    org_username is what resolve_role() dedups on; model_dump is what lets
    the framework convert a raw provider result (e.g. an LDAP group member,
    or a remote app-interface UserV1/BotV1) into the caller-supplied
    user_cls, so a provider never needs to know about any integration's
    user attributes. Providers return users only; native bots are not resolved.
    """

    @property
    def org_username(self) -> str: ...

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


@overload
def resolve_role[R: RoleMembershipFields, U: BaseModel](
    role: R,
    user_cls: type[U],
    resolved_groups: Mapping[ProviderGroup, list[ProviderMember]],
    *,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    role_cls: None = None,
) -> R: ...


@overload
def resolve_role[R: RoleMembershipFields, U: BaseModel, T: RoleMembershipFields](
    role: R,
    user_cls: type[U],
    resolved_groups: Mapping[ProviderGroup, list[ProviderMember]],
    *,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    role_cls: type[T],
) -> T: ...


@overload
def resolve_role[R: RoleMembershipFields, U: BaseModel, T: RoleMembershipFields](
    role: R,
    user_cls: type[U],
    resolved_groups: Mapping[ProviderGroup, list[ProviderMember]],
    *,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    role_cls: type[T] | None,
) -> R | T: ...


def resolve_role[R: RoleMembershipFields, U: BaseModel, T: RoleMembershipFields](
    role: R,
    user_cls: type[U],
    resolved_groups: Mapping[ProviderGroup, list[ProviderMember]],
    *,
    member_filter: Callable[[ProviderMember], bool] | None = None,
    role_cls: type[T] | None = None,
) -> R | T:
    """Return the original or supplied role type with users resolved, leaving bots unchanged.

    Shared by both the sync and async resolvers - only how resolved_groups
    gets built differs between them. Projects source attributes onto user_cls
    and validates them. Missing required nullable fields become None; users
    rejected by the target model are skipped silently. Deduplicates by org_username:
    valid explicit users are added first and win over a memberSources-resolved
    member sharing the same org_username, since they carry richer,
    integration-specific data.

    An optional member_filter excludes ineligible identities before conversion,
    such as members without GitHub accounts for GitHub-only consumers.
    """
    seen: set[str] = set()
    users: list[U] = []

    def add(source: ProviderMember) -> None:
        org_username = source.org_username
        if not org_username or org_username in seen:
            return
        if member_filter is not None and not member_filter(source):
            return
        values = source.model_dump()
        projected = {
            name: value
            for name, value in values.items()
            if name in user_cls.model_fields
        }
        for name, field in user_cls.model_fields.items():
            if (
                name not in projected
                and field.is_required()
                and type(None) in get_args(field.annotation)
            ):
                projected[name] = None
        try:
            member = user_cls.model_validate(projected, by_name=True)
        except ValidationError:
            return
        seen.add(org_username)
        users.append(member)

    for user in role.users or []:
        add(user)
    for member_source in role.member_sources or []:
        key = (member_source.provider.name, member_source.group)
        if key not in resolved_groups:
            raise ValueError(f"Membership source group could not be resolved: {key}")
        for provider_member in resolved_groups[key]:
            add(provider_member)

    data = role.model_dump(by_alias=True, round_trip=True)
    data["users"] = [user.model_dump(by_alias=True, round_trip=True) for user in users]
    return (
        role_cls.model_validate(data)
        if role_cls is not None
        else role.model_validate(data)
    )
