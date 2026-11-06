import jsonpath_ng
import jsonpath_ng.ext
import pytest
import yaml

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.change_owners import (
    manage_conditional_label,
    rebuild_change_owner_labels,
    should_show_in_review_queue,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    PathExpression,
)
from reconcile.change_owners.changes import parse_resource_file_content
from reconcile.utils.mr.labels import SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE

#
# label management tests
#


def test_label_management_add() -> None:
    assert {
        "existing-label",
        "true-label",
        "another-true-label",
    } == manage_conditional_label(
        current_labels=["existing-label"],
        conditional_labels={
            "true-label": True,
            "another-true-label": True,
            "false-label": False,
        },
        dry_run=False,
    )

    # dry-run
    assert {"existing-label"} == manage_conditional_label(
        current_labels=["existing-label"],
        conditional_labels={
            "true-label": True,
            "another-true-label": True,
            "false-label": False,
        },
        dry_run=True,
    )


def test_label_management_remove() -> None:
    assert {"existing-label"} == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "false-label": False,
        },
        dry_run=False,
    )

    # dry-run
    assert {"existing-label", "false-label"} == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "false-label": False,
        },
        dry_run=True,
    )


def test_label_management_add_and_remove() -> None:
    assert {"existing-label", "true-label"} == manage_conditional_label(
        current_labels=["existing-label", "false-label"],
        conditional_labels={
            "true-label": True,
            "false-label": False,
        },
        dry_run=False,
    )


def test_rebuild_change_owner_labels_strips_stale_and_adds_current() -> None:
    assert rebuild_change_owner_labels(
        current_labels={"change-owner/stale-label", "unrelated-label"},
        change_owner_labels=["current-label"],
    ) == {"change-owner/current-label", "unrelated-label"}


def test_rebuild_change_owner_labels_preserves_show_self_serviceable_in_review_queue() -> (
    None
):
    # Regression test for APPSRE-15674: SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE is set
    # directly by github-username-sync / ldap-users-api, not sourced from
    # bc.change_owner_labels, so it must survive change-owners' strip-and-rebuild
    # step on the very next run instead of being silently wiped.
    assert rebuild_change_owner_labels(
        current_labels={SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE, "change-owner/stale"},
        change_owner_labels=[],
    ) == {SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE}


#
# should_show_in_review_queue tests
#


def test_should_show_in_review_queue_not_self_serviceable_requires_approval() -> None:
    # not-self-serviceable: visible only once the self-service portion lands,
    # same as PENDING_SELF_SERVICE_APPROVAL's absence today.
    assert not should_show_in_review_queue(
        self_serviceable=False,
        self_service_portion_approved=False,
        role_wants_review_queue_visibility=False,
    )
    assert should_show_in_review_queue(
        self_serviceable=False,
        self_service_portion_approved=True,
        role_wants_review_queue_visibility=False,
    )


def test_should_show_in_review_queue_self_serviceable_requires_role_flag() -> None:
    # self-serviceable: visible only when a role flagged it, same as
    # SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE today.
    assert not should_show_in_review_queue(
        self_serviceable=True,
        self_service_portion_approved=True,
        role_wants_review_queue_visibility=False,
    )
    assert should_show_in_review_queue(
        self_serviceable=True,
        self_service_portion_approved=True,
        role_wants_review_queue_visibility=True,
    )


def test_should_show_in_review_queue_self_serviceable_role_flag_still_waits_for_approval() -> (
    None
):
    # even when a role flagged it, AppSRE shouldn't see it before the
    # tenant-approvable parts have landed.
    assert not should_show_in_review_queue(
        self_serviceable=True,
        self_service_portion_approved=False,
        role_wants_review_queue_visibility=True,
    )


#
# PathExpression tests
#


def test_normal_path_expression() -> None:
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
    assert jsonpath == jsonpath_ng.parse(jsonpath_expression)


def test_templated_path_expression() -> None:
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
    assert jsonpath == jsonpath_ng.ext.parse(
        "path.to.some.value[?(@.name == 'some-file.yaml')]"
    )


def test_template_path_expression_unsupported_variable() -> None:
    with pytest.raises(ValueError):
        PathExpression(
            jsonpath_expression="path[?(@.name == '{{ unsupported_variable }}')]"
        )


def test_path_expression_equals() -> None:
    a = PathExpression(jsonpath_expression="path")
    b = PathExpression(jsonpath_expression="path")
    assert a == b


def test_path_expression_not_equals() -> None:
    a = PathExpression(jsonpath_expression="path")
    b = PathExpression(jsonpath_expression="other_path")
    assert a != b


#
# Test resource file parsing
#


def test_parse_resource_file_content_structured_with_schema() -> None:
    expected_content = {"$schema": "schema-1.yml", "some_field": "some_value"}
    content, schema = parse_resource_file_content(yaml.dump(expected_content))
    assert schema == expected_content["$schema"]
    assert content == expected_content


def test_parse_resource_file_content_structured_no_schema() -> None:
    expected_content = {"some_field": "some_value"}
    content, schema = parse_resource_file_content(yaml.dump(expected_content))
    assert schema is None
    assert content == expected_content


def test_parse_resource_file_content_unstructured() -> None:
    expected_content = "something something"
    content, schema = parse_resource_file_content(expected_content)
    assert schema is None
    assert content == expected_content


def test_parse_resource_file_content_none() -> None:
    content, schema = parse_resource_file_content(None)
    assert schema is None
    assert content is None
