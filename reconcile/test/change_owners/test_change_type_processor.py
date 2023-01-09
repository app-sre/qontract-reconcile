import pytest
from jsonpath_ng.exceptions import JsonPathParserError

from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    TestFile,
    change_type_to_processor,
)

pytest_plugins = [
    "reconcile.test.change_owners.fixtures",
]


#
# change type processor validations
#


def test_change_type_processor_building_invalid_jsonpaths(
    secret_promoter_change_type: ChangeTypeV1,
):
    secret_promoter_change_type.changes[0].json_path_selectors[  # type: ignore
        0
    ] = "invalid-jsonpath/selector"
    with pytest.raises(JsonPathParserError):
        change_type_to_processor(secret_promoter_change_type)


#
# change type processor find allowed changed paths
#


def test_change_type_processor_allowed_paths_simple(
    role_member_change_type: ChangeTypeV1, user_file: TestFile
):
    changed_user_file = user_file.create_bundle_change(
        {"roles[0]": {"$ref": "some-role"}}
    )
    processor = change_type_to_processor(role_member_change_type)
    paths = processor.allowed_changed_paths(
        file_ref=changed_user_file.fileref,
        file_content=changed_user_file.new,
        ctx=ChangeTypeContext(
            change_type_processor=processor,
            context="RoleV1 - some role",
            origin="",
            approvers=[],
            context_file=user_file.file_ref(),
        ),
    )

    assert [str(p) for p in paths] == ["roles"]


def test_change_type_processor_allowed_paths_conditions(
    secret_promoter_change_type: ChangeTypeV1, namespace_file: TestFile
):
    changed_namespace_file = namespace_file.create_bundle_change(
        {"openshiftResources[1].version": 2}
    )
    processor = change_type_to_processor(secret_promoter_change_type)
    paths = processor.allowed_changed_paths(
        file_ref=changed_namespace_file.fileref,
        file_content=changed_namespace_file.new,
        ctx=ChangeTypeContext(
            change_type_processor=processor,
            context="RoleV1 - some role",
            origin="",
            approvers=[],
            context_file=namespace_file.file_ref(),
        ),
    )

    assert [str(p) for p in paths] == ["openshiftResources.[1].version"]
