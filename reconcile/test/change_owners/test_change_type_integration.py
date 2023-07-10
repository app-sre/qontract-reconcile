import pytest

from reconcile.change_owners.self_service_roles import (
    cover_changes_with_self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    DatafileObjectV1,
)
from reconcile.test.change_owners.fixtures import (
    StubFile,
    build_bundle_datafile_change,
    build_change_type,
    build_role,
    change_type_to_processor,
)


def test_change_coverage(
    secret_promoter_change_type: ChangeTypeV1,
    namespace_file: StubFile,
    role_member_change_type: ChangeTypeV1,
    user_file: StubFile,
) -> None:
    role_approver_user = "the-one-that-approves-roles"
    team_role_path = "/team-role.yml"
    role_approval_role = build_role(
        name="team-role",
        change_type_name=role_member_change_type.name,
        datafiles=[
            DatafileObjectV1(datafileSchema="/access/role-1.yml", path=team_role_path)
        ],
        users=[role_approver_user],
    )

    secret_approver_user = "the-one-that-approves-secret-promotions"
    secret_promoter_role = build_role(
        name="secret-promoter-role",
        change_type_name=secret_promoter_change_type.name,
        datafiles=[
            DatafileObjectV1(
                datafileSchema=namespace_file.fileschema,
                path=namespace_file.filepath,
            )
        ],
        users=[secret_approver_user],
    )

    bundle_changes = [
        # create a datafile change by patching the role
        user_file.create_bundle_change({"roles[0]": {"$ref": team_role_path}}),
        # create a datafile change by bumping a secret version
        namespace_file.create_bundle_change({"openshiftResources[1].version": 2}),
    ]

    cover_changes_with_self_service_roles(
        roles=[role_approval_role, secret_promoter_role],
        change_type_processors=[
            change_type_to_processor(role_member_change_type),
            change_type_to_processor(secret_promoter_change_type),
        ],
        bundle_changes=bundle_changes,
    )

    for bc in bundle_changes:
        for d in bc.diff_coverage:
            expected_approver = None
            if str(d.diff.path) == "roles.[0].$ref":
                expected_approver = role_approver_user
            elif str(d.diff.path) == "openshiftResources.[1].version":
                expected_approver = secret_approver_user
            else:
                pytest.fail(f"unexpected change path {str(d.diff.path)}")
            assert len(d.coverage) == 1
            assert len(d.coverage[0].approvers) == 1
            assert d.coverage[0].approvers[0].org_username == expected_approver


def test_remove_coverage() -> None:
    """
    Test scenario: a namespace gets removed and we want to make sure that only
    the role with the namespace-remover change-type is covering the change.
    """
    namespace_remover = build_change_type(
        name="namespace-remover",
        context_schema="/openshift/namespace-1.yml",
        context_selector="$.path",
        context_when="removed",
        change_selectors=["$"],
    )

    namespace_editor = build_change_type(
        name="namespace-editor",
        context_schema="/openshift/namespace-1.yml",
        change_selectors=["description"],
    )

    namespace_change = build_bundle_datafile_change(
        path="my-namespace.yml",
        schema="/openshift/namespace-1.yml",
        old_content={
            "description": "bar",
        },
        new_content=None,
    )
    assert namespace_change

    a_namespace_remover_user = "a-namespace-remover-user"
    namespace_remover_role = build_role(
        name="remover-role",
        change_type_name=namespace_remover.name,
        datafiles=[
            DatafileObjectV1(
                datafileSchema="/openshift/namespace-1.yml",
                path=namespace_change.fileref.path,
            )
        ],
        users=[a_namespace_remover_user],
    )

    a_namespace_editor_user = "a-namespace-editor-user"
    namespace_editor_role = build_role(
        name="editor-role",
        change_type_name=namespace_editor.name,
        datafiles=[
            DatafileObjectV1(
                datafileSchema="/openshift/namespace-1.yml",
                path=namespace_change.fileref.path,
            )
        ],
        users=[a_namespace_editor_user],
    )

    cover_changes_with_self_service_roles(
        roles=[namespace_remover_role, namespace_editor_role],
        change_type_processors=[
            namespace_remover,
            namespace_editor,
        ],
        bundle_changes=[namespace_change],
    )

    assert len(namespace_change.diff_coverage) == 1
    dc = namespace_change.diff_coverage[0]
    assert str(dc.diff.path) == "$"
    assert len(dc.coverage) == 1
    assert len(dc.coverage[0].approvers) == 1
    assert dc.coverage[0].approvers[0].org_username == a_namespace_remover_user
