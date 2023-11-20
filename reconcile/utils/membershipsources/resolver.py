from collections.abc import (
    Iterable,
    Sequence,
)
from dataclasses import dataclass
from itertools import chain

from sretoolbox.utils import threaded

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
    MembershipProviderSourceV1,
    MembershipProviderV1,
)
from reconcile.utils.grouping import group_by
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
)
from reconcile.utils.membershipsources.models import (
    ProviderResolver,
    RoleBot,
    RoleMember,
    RoleUser,
    RoleWithMemberships,
)


@dataclass
class GroupResolverJob:
    provider: MembershipProviderV1
    groups: set[str]


def build_resolver_jobs(
    roles: Sequence[RoleWithMemberships],
) -> list[GroupResolverJob]:
    """
    Bundles groups to be resolve by provider so that they can be resolved
    in batches.
    """
    groups = group_by(
        (ms for r in roles for ms in r.member_sources or []),
        key=lambda ms: ms.provider.name,
    )
    return [
        GroupResolverJob(
            provider=g[0].provider,
            groups={ms.group for ms in g},
        )
        for g in groups.values()
    ]


ProviderGroup = tuple[str, str]


def get_resolver_for_provider_source(
    source: MembershipProviderSourceV1,
) -> ProviderResolver:
    match source:
        case AppInterfaceMembershipProviderSourceV1():
            return resolve_app_interface_membership_source
        case _:
            raise ValueError(
                "No resolver available for membership provider source",
                type(source),
            )


def resolve_groups(job: GroupResolverJob) -> dict[ProviderGroup, list[RoleMember]]:
    """
    Resolves groups and returns a dict with group name as key and a list
    of members as value.
    """
    resolver = get_resolver_for_provider_source(job.provider.source)
    return resolver(job.provider.name, job.provider.source, job.groups)


def resolve_role_members(
    roles: Sequence[RoleWithMemberships], thread_pool: int = 5
) -> dict[str, list[RoleMember]]:
    """
    Resolves members of roles, combining local members and the ones from
    membership sources.
    """
    resolver_jobs = build_resolver_jobs(roles)
    processed_jobs: Iterable[dict[ProviderGroup, list[RoleMember]]] = threaded.run(
        func=resolve_groups,
        iterable=resolver_jobs,
        thread_pool_size=thread_pool,
    )
    resolved_groups: dict[ProviderGroup, list[RoleMember]] = dict(
        chain.from_iterable(d.items() for d in processed_jobs)
    )

    members_by_group = {}
    for r in roles:
        members: list[RoleMember] = []

        # bring in the local users and bots ...
        members.extend(RoleUser(**u.dict()) for u in r.users or [])
        members.extend(RoleBot(**b.dict()) for b in r.bots or [] if b.org_username)

        # ... and enhance with the ones from member sources
        for ms in r.member_sources or []:
            members.extend(resolved_groups.get((ms.provider.name, ms.group), []))

        members_by_group[r.name] = members

    return members_by_group
