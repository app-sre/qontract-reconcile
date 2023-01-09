import logging

import jsonpath_ng.ext

from reconcile.change_owners.approver import ApproverResolver
from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypeContext,
    ChangeTypeProcessor,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeImplicitOwnershipJsonPathProviderV1,
)


def cover_changes_with_implicit_ownership(
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
    approver_resolver: ApproverResolver,
) -> None:
    for bc, ctx in change_type_contexts_for_implicit_ownership(
        change_type_processors=change_type_processors,
        bundle_changes=bundle_changes,
        approver_resolver=approver_resolver,
    ):
        bc.cover_changes(ctx)


def change_type_contexts_for_implicit_ownership(
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
    approver_resolver: ApproverResolver,
) -> list[tuple[BundleFileChange, ChangeTypeContext]]:
    change_type_contexts: list[tuple[BundleFileChange, ChangeTypeContext]] = []
    processors_with_implicit_ownership = [
        ctp for ctp in change_type_processors if ctp.implicit_ownership
    ]
    for ctp in processors_with_implicit_ownership:
        for bc in bundle_changes:
            for context_file_ref in bc.extract_context_file_refs(ctp):
                for io in ctp.implicit_ownership:
                    if isinstance(io, ChangeTypeImplicitOwnershipJsonPathProviderV1):
                        if context_file_ref != bc.fileref:
                            logging.warning(
                                f"{io.provider} provider based implicit ownership is not supported for ownership context files that are not the changed file."
                            )
                            continue
                        implicit_owner_refs = (
                            find_approvers_with_implicit_ownership_jsonpath_selector(
                                bc=bc,
                                implicit_ownership=io,
                            )
                        )
                    else:
                        raise NotImplementedError(
                            f"unsupported implicit ownership provider: {io}"
                        )
                    implicit_approvers = list(
                        filter(
                            None,
                            [
                                approver_resolver.lookup_approver_by_path(owner_path)
                                for owner_path in implicit_owner_refs
                            ],
                        )
                    )
                    if implicit_approvers:
                        change_type_contexts.append(
                            (
                                bc,
                                ChangeTypeContext(
                                    change_type_processor=ctp,
                                    context=f"implicit ownership - { ','.join(a.org_username for a in implicit_approvers ) }",
                                    approvers=implicit_approvers,
                                    context_file=context_file_ref,
                                ),
                            )
                        )

    return change_type_contexts


def find_approvers_with_implicit_ownership_jsonpath_selector(
    bc: BundleFileChange,
    implicit_ownership: ChangeTypeImplicitOwnershipJsonPathProviderV1,
) -> set[str]:

    context_file_content = bc.old or bc.new
    if context_file_content is None:
        # this can't happen. either bc.old or bc.new is set
        # but to make mypy happy, we need to check for None
        return set()

    return {
        owner_ref.value
        for owner_ref in jsonpath_ng.ext.parse(
            implicit_ownership.json_path_selector
        ).find(context_file_content)
    }
