import pytest
import yaml

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.change_owners import manage_conditional_label
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    PathExpression,
)
from reconcile.change_owners.changes import parse_resource_file_content

#
# label management tests
#


def test_label_management_add():
    assert [
        "existing-label",
        "true-label",
        "another-true-label",
    ] == manage_conditional_label(
        current_labels=["existing-label"],
        conditional_labels={
            "true-label": True,
            "another-true-label": True,
            "false-label": False,
        },
        dry_run=False,
    )

    # dry-run
    assert ["existing-label"] == manage_conditional_label(
        current_labels=["existing-label"],
        conditional_labels={
            "true-label": True,
            "another-true-label": True,
            "false-label": False,
        },
        dry_run=True,
    )


def test_label_management_remove():
    assert ["existing-label"] == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "false-label": False,
        },
        dry_run=False,
    )

    # dry-run
    assert ["existing-label", "false-label"] == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "false-label": False,
        },
        dry_run=True,
    )


def test_label_management_add_and_remove():
    assert ["existing-label", "true-label"] == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "true-label": True,
            "false-label": False,
        },
        dry_run=False,
    )


#
# PathExpression tests
#


def test_normal_path_expression():
    jsonpath_expression = "path.to.some.value"
    pe = PathExpression(
        jsonpath_expression=jsonpath_expression,
    )
    jsonpath = pe.jsonpath_for_context(
        ChangeTypeContext(
            change_type_processor=None,  # type: ignore
            context="RoleV1 - some-role",
            origin="",
            approvers=[],
            context_file=FileRef(
                BundleFileType.DATAFILE, "some-file.yaml", "schema-1.yml"
            ),
        )
    )
    assert jsonpath_expression == str(jsonpath)


def test_templated_path_expression():
    jsonpath_expression = "path.to.some.value[?(@.name == '{{ ctx_file_path }}')]"
    pe = PathExpression(
        jsonpath_expression=jsonpath_expression,
    )
    jsonpath = pe.jsonpath_for_context(
        ChangeTypeContext(
            change_type_processor=None,  # type: ignore
            context="RoleV1 - some-role",
            origin="",
            approvers=[],
            context_file=FileRef(
                BundleFileType.DATAFILE, "some-file.yaml", "schema-1.yml"
            ),
        )
    )
    assert (
        "path.to.some.value.[?[Expression(Child(This(), Fields('name')) == 'some-file.yaml')]]"
        == str(jsonpath)
    )


def test_template_path_expression_unsupported_variable():
    with pytest.raises(ValueError):
        PathExpression(
            jsonpath_expression="path[?(@.name == '{{ unsupported_variable }}')]"
        )


def test_path_expression_equals():
    a = PathExpression(jsonpath_expression="path")
    b = PathExpression(jsonpath_expression="path")
    assert a == b


def test_path_expression_not_equals():
    a = PathExpression(jsonpath_expression="path")
    b = PathExpression(jsonpath_expression="other_path")
    assert a != b


#
# Test resource file parsing
#


def test_parse_resource_file_content_structured_with_schema():
    expected_content = {"$schema": "schema-1.yml", "some_field": "some_value"}
    content, schema = parse_resource_file_content(yaml.dump(expected_content))
    assert schema == expected_content["$schema"]
    assert content == expected_content


def test_parse_resource_file_content_structured_no_schema():
    expected_content = {"some_field": "some_value"}
    content, schema = parse_resource_file_content(yaml.dump(expected_content))
    assert schema is None
    assert content == expected_content


def test_parse_resource_file_content_unstructured():
    expected_content = "something something"
    content, schema = parse_resource_file_content(expected_content)
    assert schema is None
    assert content == expected_content


def test_parse_resource_file_content_none():
    content, schema = parse_resource_file_content(None)
    assert schema is None
    assert content is None
