import logging

from reconcile.change_owners.approver import ApproverResolver
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypeProcessor,
    FileChange,
)
from reconcile.change_owners.changes import BundleFileChange
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeImplicitOwnershipJsonPathProviderV1,
)
from reconcile.utils.jsonpath import parse_jsonpath


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
            for ownership in ctp.find_context_file_refs(
                change=FileChange(
                    file_ref=bc.fileref,
                    old=bc.old,
                    new=bc.new,
                ),
                expansion_trail=set(),
            ):
                for io in ctp.implicit_ownership:
                    if isinstance(io, ChangeTypeImplicitOwnershipJsonPathProviderV1):
                        if ownership.context_file_ref != bc.fileref:
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
                                    context=f"implicit ownership - (via {ownership.change_type.name})",
                                    origin=ownership.change_type.name,
                                    approvers=implicit_approvers,
                                    context_file=ownership.context_file_ref,
                                ),
                            )
                        )

    return change_type_contexts


def find_approvers_with_implicit_ownership_jsonpath_selector(
    bc: BundleFileChange,
    implicit_ownership: ChangeTypeImplicitOwnershipJsonPathProviderV1,
) -> set[str]:
    context_file_content = bc.old_content_with_metadata or bc.new_content_with_metadata
    if context_file_content is None:
        # this can't happen. either bc.old or bc.new is set
        # but to make mypy happy, we need to check for None
        return set()

    return {
        owner_ref.value
        for owner_ref in parse_jsonpath(implicit_ownership.json_path_selector).find(
            context_file_content
        )
    }
