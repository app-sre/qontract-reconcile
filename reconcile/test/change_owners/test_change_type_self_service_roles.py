import pytest

from reconcile.change_owners.change_owners import validate_self_service_role
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    ChangeTypeV1,
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
)

#
# test self-service role validation
#


def test_valid_self_service_role():
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
        users=[],
        bots=[],
    )
    validate_self_service_role(role)


def test_invalid_self_service_role():
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
        users=[],
        bots=[],
    )
    with pytest.raises(ValueError):
        validate_self_service_role(role)
