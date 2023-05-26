import pytest

from reconcile.change_owners.approver import (
    GitlabGroupApproverReachability,
    SlackGroupApproverReachability,
)
from reconcile.change_owners.self_service_roles import (
    DatafileIncompatibleWithChangeTypeError,
    NoApproversInSelfServiceRoleError,
    approver_reachability_from_role,
    validate_self_service_role,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    ChangeTypeV1,
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
    UserV1,
)
from reconcile.test.change_owners.fixtures import build_role

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
        users=[UserV1(org_username="u", tag_on_merge_requests=False)],
        bots=[],
        permissions=[],
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
        users=[UserV1(org_username="u", tag_on_merge_requests=False)],
        bots=[],
        permissions=[],
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
