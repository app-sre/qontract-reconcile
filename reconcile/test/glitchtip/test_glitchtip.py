import json
from collections.abc import Callable
from unittest.mock import Mock

from reconcile.glitchtip.integration import (
    fetch_current_state,
    fetch_desired_state,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import GlitchtipProjectsV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import GlitchtipClient
from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)


def test_fetch_current_state(
    glitchtip_client: GlitchtipClient,
    glitchtip_server_full_api_response: None,
    fx: Fixtures,
) -> None:
    current_state = fetch_current_state(
        glitchtip_client, ignore_users=["sd-app-sre+glitchtip@nasa.com"]
    )

    assert json.dumps(
        [s.dict() for s in current_state], indent=2, sort_keys=True
    ) == fx.get("current_state_expected.json")


def test_desire_state(
    fx: Fixtures,
    internal_groups_client: Mock,
    gql_class_factory: Callable,
) -> None:
    projects = [
        gql_class_factory(GlitchtipProjectsV1, i)
        for i in fx.get_anymarkup("desire_state_projects.yml")
    ]
    from_emea_ldap_group = Group(
        name="from_emea",
        description="foo bar",
        member_approval_type="self-service",
        contact_list="email@example.org",
        owners=[Entity(type=EntityType.SERVICE_ACCOUNT, id="service-account-1")],
        display_name="ai-dev-test-group (App-Interface))",
        notes=None,
        rover_group_member_query=None,
        rover_group_inclusions=None,
        rover_group_exclusions=None,
        members=[
            Entity(type=EntityType.USER, id="pike"),
            Entity(type=EntityType.USER, id="uhura"),
        ],
        member_of=None,
        namespace=None,
    )
    internal_groups_client.group.side_effect = [from_emea_ldap_group]
    desired_state = fetch_desired_state(
        glitchtip_projects=projects,
        mail_domain="nasa.com",
        internal_groups_client=internal_groups_client,
    )

    assert json.dumps(
        [s.dict() for s in desired_state], indent=2, sort_keys=True
    ) == fx.get("desire_state_expected.json")
