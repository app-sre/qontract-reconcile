from typing import Optional

import jsonpath_ng.ext
import pytest

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.change_types import (
    ChangeTypeProcessor,
    OwnershipContext,
)
from reconcile.change_owners.changes import BundleFileChange
from reconcile.change_owners.implicit_ownership import (
    change_type_contexts_for_implicit_ownership,
    find_approvers_with_implicit_ownership_jsonpath_selector,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeImplicitOwnershipJsonPathProviderV1,
    ChangeTypeImplicitOwnershipV1,
)
from reconcile.test.change_owners.fixtures import (
    build_change_type,
    build_test_datafile,
)

#
# test finding implicit approver in bundle change
#


def test_find_implict_single_approver_with_jsonpath() -> None:
    bc = BundleFileChange(
        fileref=FileRef(
            file_type=BundleFileType.DATAFILE,
            path="/file.yml",
            schema="some-schema",
        ),
        old=None,
        new={"approver": "/user/approver.yml"},
        old_content_sha="",
        new_content_sha="new",
        diffs=[],
    )
    approver = find_approvers_with_implicit_ownership_jsonpath_selector(
        bc=bc,
        implicit_ownership=ChangeTypeImplicitOwnershipJsonPathProviderV1(
            provider="jsonPath",
            jsonPathSelector="$.approver",
        ),
    )

    assert approver == {"/user/approver.yml"}


def test_find_implict_multiple_approvers_with_jsonpath() -> None:
    bc = BundleFileChange(
        fileref=FileRef(
            file_type=BundleFileType.DATAFILE,
            path="/file.yml",
            schema="some-schema",
        ),
        old=None,
        new={"approvers": ["/user/approver-1.yml", "/user/approver-2.yml"]},
        old_content_sha="",
        new_content_sha="new",
        diffs=[],
    )
    approvers = find_approvers_with_implicit_ownership_jsonpath_selector(
        bc=bc,
        implicit_ownership=ChangeTypeImplicitOwnershipJsonPathProviderV1(
            provider="jsonPath",
            jsonPathSelector="$.approvers[*]",
        ),
    )

    assert approvers == {"/user/approver-1.yml", "/user/approver-2.yml"}


def test_find_implict_approver_with_jsonpath_no_data() -> None:
    """
    in this test, no approvers should be found because no data is provided
    """
    bc = BundleFileChange(
        fileref=FileRef(
            file_type=BundleFileType.DATAFILE,
            path="/file.yml",
            schema="some-schema",
        ),
        old=None,
        new=None,
        old_content_sha="",
        new_content_sha="",
        diffs=[],
    )
    approver = find_approvers_with_implicit_ownership_jsonpath_selector(
        bc=bc,
        implicit_ownership=ChangeTypeImplicitOwnershipJsonPathProviderV1(
            provider="jsonPath",
            jsonPathSelector="$.approver",
        ),
    )

    assert not approver


#
# test finding change type contexts for implicit ownership
#


class MockApproverResolver:
    def __init__(self, approvers: dict[str, Approver]):
        self.approvers = approvers

    def lookup_approver_by_path(self, path: str) -> Optional[Approver]:
        return self.approvers.get(path)


@pytest.fixture
def change_type() -> ChangeTypeProcessor:
    ct = build_change_type("change-type", [], context_schema="schame-1.yml")
    ct.implicit_ownership = [
        ChangeTypeImplicitOwnershipJsonPathProviderV1(
            provider="jsonPath",
            jsonPathSelector="$.approver",
        )
    ]
    return ct


def test_find_implict_change_type_context_jsonpath_provider(
    change_type: ChangeTypeProcessor,
) -> None:
    approver_path = "/user/approver.yml"
    approver = Approver("approver", False)

    bc = build_test_datafile(
        filepath="file.yml",
        schema=change_type.context_schema,
        content={"some": "data", "approver": approver_path},
    ).create_bundle_change(jsonpath_patches={"$.some": "new-data"})

    result = change_type_contexts_for_implicit_ownership(
        change_type_processors=[change_type],
        bundle_changes=[bc],
        approver_resolver=MockApproverResolver(approvers={approver_path: approver}),
    )

    assert result[0][0] == bc

    ctx = result[0][1]

    assert ctx.approvers == [approver]
    assert ctx.change_type_processor.name == change_type.name
    assert ctx.context_file == bc.fileref


def test_find_implict_change_type_context_jsonpath_provider_invalid_context_file(
    change_type: ChangeTypeProcessor,
) -> None:
    """
    the jsonpath provider for implicit ownership only supports change-types
    that don't try to find the ownership context in a datafile different from
    the one that contains the changes to cover.
    this test makes sure we handle that correctly at the level of extracting the
    approvers from the changed file.
    note: there is another test about validating change-types so that such a
    situation is already prevented at the level of loading the change-types, hence
    failing the PR check that would introduce such a change-type.
    """

    approver_path = "/user/approver.yml"
    approver = Approver("approver", False)
    change_schema = "change-schema-1.yml"

    change_type.change_detectors[0].change_schema = change_schema
    change_type.change_detectors[0].context = OwnershipContext(
        selector=jsonpath_ng.ext.parse("$.approver"), when=None
    )

    bc = build_test_datafile(
        filepath="file.yml",
        schema=change_schema,
        content={"some": "data", "approver": approver_path},
    ).create_bundle_change(jsonpath_patches={"$.some": "new-data"})

    assert not change_type_contexts_for_implicit_ownership(
        change_type_processors=[change_type],
        bundle_changes=[bc],
        approver_resolver=MockApproverResolver(approvers={approver_path: approver}),
    )


def test_find_implict_change_type_context_unknown_provider(
    change_type: ChangeTypeProcessor,
) -> None:
    change_type.implicit_ownership = [
        ChangeTypeImplicitOwnershipV1(
            provider="unknown-provider",
        )
    ]

    bc = build_test_datafile(
        filepath="file.yml",
        schema=change_type.context_schema,
        content={"some": "data", "approver": "/user/approver.yml"},
    ).create_bundle_change(jsonpath_patches={"$.some": "new-data"})

    with pytest.raises(NotImplementedError):
        change_type_contexts_for_implicit_ownership(
            change_type_processors=[change_type],
            bundle_changes=[bc],
            approver_resolver=MockApproverResolver(approvers={}),
        )


def test_find_implict_change_type_context_jsonpath_provider_unresolvable_approvers(
    change_type: ChangeTypeProcessor,
) -> None:
    bc = build_test_datafile(
        filepath="file.yml",
        schema=change_type.context_schema,
        content={"some": "data", "approver": "/user/approver.yml"},
    ).create_bundle_change(jsonpath_patches={"$.some": "new-data"})

    assert not change_type_contexts_for_implicit_ownership(
        change_type_processors=[change_type],
        bundle_changes=[bc],
        approver_resolver=MockApproverResolver(approvers={}),
    )
