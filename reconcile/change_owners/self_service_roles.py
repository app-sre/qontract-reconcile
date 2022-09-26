from collections import defaultdict
from typing import Tuple

from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1

from reconcile.change_owners.change_types import (
    BundleFileChange,
    BundleFileType,
    Approver,
    ChangeTypeProcessor,
    ChangeTypeContext,
)


def cover_changes_with_self_service_roles(
    roles: list[RoleV1],
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
) -> None:
    """
    Cover changes with ChangeTypeV1 associated to datafiles and resources via a
    RoleV1 saas_file_owners and self_service configuration.
    """

    # role lookup enables fast lookup roles for (filetype, filepath, changetype-name)
    role_lookup: dict[Tuple[BundleFileType, str, str], list[RoleV1]] = defaultdict(list)
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
    for bc in bundle_changes:
        for ctp in change_type_processors:
            datafile_refs = bc.extract_context_file_refs(ctp.change_type)
            for df_ref in datafile_refs:
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                for role in role_lookup[
                    (df_ref.file_type, df_ref.path, ctp.change_type.name)
                ]:
                    approvers = [
                        Approver(u.org_username, u.tag_on_merge_requests)
                        for u in role.users or []
                        if u
                    ]
                    approvers.extend(
                        [
                            Approver(b.org_username, False)
                            for b in role.bots or []
                            if b and b.org_username
                        ]
                    )
                    bc.cover_changes(
                        ChangeTypeContext(
                            change_type_processor=ctp,
                            context=f"RoleV1 - {role.name}",
                            approvers=approvers,
                        )
                    )
