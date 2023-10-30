import json

import pytest

from reconcile.change_owners.approver import (
    GitlabGroupApproverReachability,
    SlackGroupApproverReachability,
)
from reconcile.change_owners.self_service_roles import (
    CHANGE_OWNERS_LABELS_LABEL,
    DatafileIncompatibleWithChangeTypeError,
    NoApproversInSelfServiceRoleError,
    approver_reachability_from_role,
    change_type_labels_from_role,
    cover_changes_with_self_service_roles,
    validate_self_service_role,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    ChangeTypeV1,
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
    UserV1,
)
from reconcile.test.change_owners.fixtures import (
    build_change_type,
    build_role,
    build_test_datafile,
)

#
# test self-service role validation
#


def test_valid_self_service_role() -> None:
    role = RoleV1(
        name="role",
        path="/role.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=ChangeTypeV1(
                    name="change-type",
                    contextSchema="schema-1.yml",
                ),
                datafiles=[
                    DatafileObjectV1(
                        datafileSchema="schema-1.yml",
                        path="datafile.yaml",
                    )
                ],
                resources=None,
            )
        ],
        users=[UserV1(name="u", org_username="u", tag_on_merge_requests=False)],
        bots=[],
        permissions=[],
        labels=None,
        memberSources=[],
    )
    validate_self_service_role(role)


def test_invalid_self_service_role_schema_mismatch() -> None:
    role = RoleV1(
        name="role",
        path="/role.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=ChangeTypeV1(
                    name="change-type",
                    contextSchema="schema-1.yml",
                ),
                datafiles=[
                    DatafileObjectV1(
                        datafileSchema="another-schema-1.yml",
                        path="datafile.yaml",
                    )
                ],
                resources=None,
            )
        ],
        users=[UserV1(name="u", org_username="u", tag_on_merge_requests=False)],
        bots=[],
        permissions=[],
        labels=None,
        memberSources=[],
    )
    with pytest.raises(DatafileIncompatibleWithChangeTypeError):
        validate_self_service_role(role)


def test_invalid_self_service_role_no_approvers() -> None:
    with pytest.raises(NoApproversInSelfServiceRoleError):
        role = build_role(
            name="team-role",
            change_type_name="change-type-name",
            datafiles=[
                DatafileObjectV1(datafileSchema="/access/role-1.yml", path="path")
            ],
            users=[],
        )
        validate_self_service_role(role)


#
# change type context resolution
#


def test_change_type_contexts_for_self_service_roles_schema() -> None:
    role = RoleV1(
        name="role",
        path="/role.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=ChangeTypeV1(
                    name="schema-admin",
                    contextSchema="schema-1.yml",
                ),
                datafiles=None,
                resources=None,
            )
        ],
        users=[UserV1(name="u", org_username="u", tag_on_merge_requests=False)],
        bots=[],
        permissions=[],
        labels=None,
        memberSources=[],
    )
    ctp = build_change_type(
        name="schema-admin",
        change_selectors=["allowed_path"],
        context_schema="schema-1.yml",
    )
    df = build_test_datafile(
        content={
            "restricted_path": "value",
            "allowed_path": "value",
        },
        filepath="file-1.yaml",
        schema="schema-1.yml",
    )

    self_serviceable_change = df.create_bundle_change(
        jsonpath_patches={"allowed_path": "new_value"}
    )
    cover_changes_with_self_service_roles(
        roles=[role],
        change_type_processors=[ctp],
        bundle_changes=[self_serviceable_change],
    )
    assert self_serviceable_change.all_changes_covered()

    not_self_serviceable_change = df.create_bundle_change(
        jsonpath_patches={"restricted_path": "new_value"}
    )
    cover_changes_with_self_service_roles(
        roles=[role],
        change_type_processors=[ctp],
        bundle_changes=[not_self_serviceable_change],
    )
    assert not not_self_serviceable_change.all_changes_covered()


#
# test self-service role approver-reachability
#


def test_self_service_role_slack_user_group_approver_reachability() -> None:
    slack_groups = ["slack-group-1", "slack-group-2"]
    slack_workspace = "slack-workspace"
    role = build_role(
        name="role",
        datafiles=None,
        change_type_name="change-type-name",
        slack_groups=slack_groups,
        slack_workspace=slack_workspace,
    )
    reachability = approver_reachability_from_role(role)
    assert reachability == [
        SlackGroupApproverReachability(slack_group=g, workspace=slack_workspace)
        for g in slack_groups
    ]


def test_self_service_role_gitlab_user_group_approver_reachability() -> None:
    gitlab_groups = ["slack-group-1", "slack-group-2"]
    role = build_role(
        name="role",
        datafiles=None,
        change_type_name="change-type-name",
        gitlab_groups=gitlab_groups,
    )
    reachability = approver_reachability_from_role(role)
    assert reachability == [
        GitlabGroupApproverReachability(gitlab_group=g) for g in gitlab_groups
    ]


#
# test self-service role change-owner labels
#


def test_self_service_role_change_owner_labels() -> None:
    role = build_role(
        name="role",
        datafiles=None,
        change_type_name="change-type-name",
        labels=json.dumps({CHANGE_OWNERS_LABELS_LABEL: "label1,label2, label3"}),
    )
    assert {"label1", "label2", "label3"} == change_type_labels_from_role(role)


def test_self_service_role_no_change_owner_labels() -> None:
    role = build_role(
        name="role",
        datafiles=None,
        change_type_name="change-type-name",
        labels=json.dumps({}),
    )
    assert not change_type_labels_from_role(role)


def test_self_service_role_empty_change_owner_labels() -> None:
    role = build_role(
        name="role",
        datafiles=None,
        change_type_name="change-type-name",
        labels=json.dumps({CHANGE_OWNERS_LABELS_LABEL: ""}),
    )
    assert not change_type_labels_from_role(role)
