from collections import defaultdict

from reconcile.change_owners.approver import (
    ApproverReachability,
    GitlabGroupApproverReachability,
    SlackGroupApproverReachability,
)
from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
    Approver,
    ChangeTypeContext,
    ChangeTypeProcessor,
    FileChange,
)
from reconcile.change_owners.changes import BundleFileChange
from reconcile.gql_definitions.change_owners.queries import self_service_roles
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    PermissionGitlabGroupMembershipV1,
    PermissionSlackUsergroupV1,
    RoleV1,
)
from reconcile.utils import expiration, gql
from reconcile.utils.membershipsources.models import (
    RoleBot,
    RoleMember,
    RoleUser,
)
from reconcile.utils.membershipsources.resolver import resolve_role_members

CHANGE_OWNERS_LABELS_LABEL = "change-owners-labels"


class NoApproversInSelfServiceRoleError(Exception):
    """
    Thrown when a self-service role has no approvers
    """


class DatafileIncompatibleWithChangeTypeError(Exception):
    """
    Thrown when a datafile and a change type are hooked up
    in a self-service role, but are not compatible schema wise.
    """


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles: list[RoleV1] = []
    for r in expiration.filter(self_service_roles.query(gql_api.query).roles or []):
        if not r.self_service:
            continue
        validate_self_service_role(r)
        roles.append(r)
    return roles


def validate_self_service_role(role: RoleV1) -> None:
    """
    Validate that a self-service role has approvers and that the referenced
    change-types and datafiles/resources are compatible.
    """
    if not role.users and not role.bots and not role.member_sources:
        raise NoApproversInSelfServiceRoleError(
            f"The role {role.name} has no users, bots or memberSources definitions "
            "to drive the self-service process. Add approvers to the roles."
        )
    for ssc in role.self_service or []:
        if ssc.change_type.context_schema:
            # check that all referenced datafiles have a schema that
            # is compatible with the change-type
            incompatible_datafiles = [
                df.path
                for df in ssc.datafiles or []
                if df.datafile_schema != ssc.change_type.context_schema
            ]
            if incompatible_datafiles:
                raise DatafileIncompatibleWithChangeTypeError(
                    f"The datafiles {incompatible_datafiles} are not compatible with the "
                    f"{ssc.change_type.name} change-types contextSchema {ssc.change_type.context_schema}"
                )


def cover_changes_with_self_service_roles(
    roles: list[RoleV1],
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
) -> None:
    for bc, ctx in change_type_contexts_for_self_service_roles(
        roles=roles,
        change_type_processors=change_type_processors,
        bundle_changes=bundle_changes,
    ):
        bc.cover_changes(ctx)


def change_type_contexts_for_self_service_roles(
    roles: list[RoleV1],
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
) -> list[tuple[BundleFileChange, ChangeTypeContext]]:
    """
    Cover changes with ChangeTypeV1 associated to datafiles and resources via a
    RoleV1 saas_file_owners and self_service configuration.
    """

    # role lookup enables fast lookup roles for (filetype, filepath, changetype-name)
    role_lookup: dict[tuple[BundleFileType, str, str], list[RoleV1]] = defaultdict(list)
    # schema role lookup enables fast lookup roles for a (schema, changetype-name)
    schema_role_lookup: dict[tuple[str, str], list[RoleV1]] = defaultdict(list)
    change_types_by_name: dict[str, ChangeTypeProcessor] = {
        ctp.name: ctp for ctp in change_type_processors
    }

    for r in roles:
        # build role lookup for self_service section of a role
        if r.self_service:
            for ss in r.self_service:
                if ss.datafiles:
                    for df in ss.datafiles:
                        role_lookup[
                            BundleFileType.DATAFILE, df.path, ss.change_type.name
                        ].append(r)
                if ss.resources:
                    for res in ss.resources:
                        role_lookup[
                            BundleFileType.RESOURCEFILE, res, ss.change_type.name
                        ].append(r)
                if (
                    ss.change_type.context_schema
                    and not ss.datafiles
                    and not ss.resources
                ):
                    # change types mentioned without datafiels or resources apply
                    # to all datafiles and resources of the given schema
                    schema_role_lookup[
                        ss.change_type.context_schema, ss.change_type.name
                    ].append(r)

    # resolve approvers for self-service roles, either directly or via member sources
    resolved_approvers = resolve_role_members([r for r in roles if r.self_service])

    # match every BundleChange with every relevant ChangeTypeV1
    change_type_contexts = []
    for bc in bundle_changes:
        for ctp in change_type_processors:
            for ownership in ctp.find_context_file_refs(
                change=FileChange(
                    file_ref=bc.fileref,
                    old=bc.old,
                    new=bc.new,
                    old_backrefs=bc.old_backrefs,
                    new_backrefs=bc.new_backrefs,
                ),
                expansion_trail=set(),
            ):
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                owning_roles: dict[str, RoleV1] = {}
                for ct_lineage in change_types_by_name[
                    ownership.change_type.name
                ].lineage:
                    owning_roles.update({
                        role.name: role
                        for role in role_lookup[
                            ownership.owned_file_ref.file_type,
                            ownership.owned_file_ref.path,
                            ct_lineage,
                        ]
                    })
                owning_roles.update({
                    role.name: role
                    for role in (
                        schema_role_lookup[
                            ownership.owned_file_ref.schema,
                            ownership.change_type.name,
                        ]
                        if ownership.owned_file_ref.schema
                        else []
                    )
                })
                for role in owning_roles.values():
                    change_type_contexts.append((
                        bc,
                        ChangeTypeContext(
                            change_type_processor=ctp,
                            context=f"RoleV1 - {role.name}",
                            origin=ownership.change_type.name,
                            approvers=[
                                approver
                                for rm in resolved_approvers.get(role.name, [])
                                if (approver := build_approver(rm)) is not None
                            ],
                            approver_reachability=approver_reachability_from_role(role),
                            change_owner_labels=change_type_labels_from_role(role),
                            context_file=ownership.context_file_ref,
                        ),
                    ))
    return change_type_contexts


def build_approver(role_member: RoleMember) -> Approver | None:
    """
    Builds an approver from a role member. Can return None if the passed
    approver is not considered valid within this context, e.g. not having
    an org username.
    """
    match role_member:
        case RoleUser():
            return Approver(role_member.org_username, role_member.tag_on_merge_requests)
        case RoleBot() if role_member.org_username:
            return (
                Approver(role_member.org_username, False)
                if role_member.org_username
                else None
            )
    return None


def change_type_labels_from_role(role: RoleV1) -> set[str]:
    change_owner_labels = (
        role.labels[CHANGE_OWNERS_LABELS_LABEL]
        if role.labels and CHANGE_OWNERS_LABELS_LABEL in role.labels
        else None
    )
    if change_owner_labels:
        return {label.strip() for label in change_owner_labels.split(",")}
    return set()


def approver_reachability_from_role(role: RoleV1) -> list[ApproverReachability]:
    reachability: list[ApproverReachability] = []
    for permission in role.permissions or []:
        if isinstance(permission, PermissionSlackUsergroupV1):
            reachability.append(
                SlackGroupApproverReachability(
                    slack_group=permission.handle,
                    workspace=permission.workspace.name,
                    channel=permission.channels[0],
                )
            )
        elif isinstance(permission, PermissionGitlabGroupMembershipV1):
            reachability.append(
                GitlabGroupApproverReachability(gitlab_group=permission.group)
            )

    return reachability
