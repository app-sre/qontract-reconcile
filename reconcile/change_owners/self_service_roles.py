from collections import defaultdict

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
    Approver,
    BundleFileChange,
    ChangeTypeContext,
    ChangeTypeProcessor,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1


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
    for r in roles:
        # build role lookup for self_service section of a role
        if r.self_service:
            for ss in r.self_service:
                if ss.datafiles:
                    for df in ss.datafiles:
                        role_lookup[
                            (BundleFileType.DATAFILE, df.path, ss.change_type.name)
                        ].append(r)
                if ss.resources:
                    for res in ss.resources:
                        role_lookup[
                            (BundleFileType.RESOURCEFILE, res, ss.change_type.name)
                        ].append(r)

    # match every BundleChange with every relevant ChangeTypeV1
    change_type_contexts = []
    for bc in bundle_changes:
        for ctp in change_type_processors:
            datafile_refs = bc.extract_context_file_refs(ctp)
            for df_ref in datafile_refs:
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                for role in role_lookup[(df_ref.file_type, df_ref.path, ctp.name)]:
                    approvers = [
                        Approver(u.org_username, u.tag_on_merge_requests)
                        for u in role.users or []
                    ]
                    approvers.extend(
                        [
                            Approver(b.org_username, False)
                            for b in role.bots or []
                            if b.org_username
                        ]
                    )
                    change_type_contexts.append(
                        (
                            bc,
                            ChangeTypeContext(
                                change_type_processor=ctp,
                                context=f"RoleV1 - {role.name}",
                                approvers=approvers,
                                context_file=df_ref,
                            ),
                        )
                    )
    return change_type_contexts
