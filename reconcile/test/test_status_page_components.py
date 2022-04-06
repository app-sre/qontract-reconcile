from datetime import datetime, timedelta, timezone
from typing import Optional
import re
from unittest.mock import ANY

from reconcile.utils.statuspage.atlassian import AtlassianComponent, AtlassianStatusPage
from reconcile.utils.statuspage.models import (
    StatusComponent,
    StatusPage,
    StatusPageComponentStatusProvider,
    StatusPageComponentStatusProviderManualConfig,
)
from reconcile.status_page_components import register_providers
from reconcile.utils.vaultsecretref import VaultSecretRef
from .fixtures import Fixtures

import pytest

fxt = Fixtures("statuspage")

register_providers()


def get_page_fixtures(path: str) -> list[StatusPage]:
    pages = fxt.get_anymarkup(path)["appInterface"]["pages"]
    return [StatusPage(**p) for p in pages]


def get_atlassian_component_fixtures(
    path: str, page_id: str
) -> list[AtlassianComponent]:
    components = fxt.get_anymarkup(path)["atlassianApi"]["components"][page_id]
    return [AtlassianComponent(**p) for p in components]


class StateStub:
    """
    dict based mock for reconcile.utils.state
    """

    def __init__(self, state=None):
        if state is not None:
            self.state = state
        else:
            self.state = {}

    def get(self, key):
        return self.state.get(key)

    def get_all(self, _):
        return self.state

    def add(self, key, value, force=False):
        self.state[key] = value

    def rm(self, key):
        del self.state[key]


def get_state_fixture(path: str) -> StateStub:
    return StateStub(fxt.get_anymarkup(path)["appInterface"]["state"])


def component_to_dict(
    component: StatusComponent,
    group_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Optional[str]]:
    data = dict(
        name=component.display_name,
        description=component.description,
    )
    if group_id:
        data["group_id"] = group_id
    if status:
        data["status"] = status
    return data


def stub_resolve_secret():
    def f(self):
        return {"token": "token"}

    return f


def test_create_component(mocker):
    """
    Test if the creation logic is called for a component missing on the
    status page.
    """
    fixture_name = "test_create_component.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    create_mock = mocker.patch.object(
        AtlassianStatusPage, "_create_component", autospec=True
    )
    create_mock.return_value = None
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )

    page = get_page_fixtures(fixture_name)[0]
    page.reconcile(False, StateStub())

    create_mock.assert_called_with(
        ANY, component_to_dict(page.components[0], group_id="group_id_1")
    )


def test_bind_component(mocker):
    """
    Test if bind logic is called for a component that already exists on
    the status page but is not bound to the one in desired state.
    """
    fixture_name = "test_bind_component.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    bind_mock = mocker.patch.object(StatusPage, "_bind_component", autospec=True)
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )

    page = get_page_fixtures(fixture_name)[0]
    state = StateStub()

    # execute bind logic through reconciling
    page.reconcile(False, state)

    # check if binding was called
    bind_mock.assert_called_with(ANY, False, page.components[0], "comp_id_1", state)


def test_update_component(mocker):
    """
    Test if updates are triggered for components when their name, group
    or description changes. The fixture for this test includes three
    components, that need update for different reasons, and one component
    that is up to date.
    """
    fixture_name = "test_update_component.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    update_mock = mocker.patch.object(
        AtlassianStatusPage, "_update_component", autospec=True
    )
    update_mock.return_value = None
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )

    page = get_page_fixtures(fixture_name)[0]
    assert len(page.components) == 4

    page.reconcile(False, get_state_fixture(fixture_name))

    update_mock.assert_any_call(
        ANY,
        page.components[0].component_id,
        component_to_dict(page.components[0], group_id="group_id_1"),
    )
    update_mock.assert_any_call(
        ANY,
        page.components[1].component_id,
        component_to_dict(page.components[1], group_id="group_id_1"),
    )
    update_mock.assert_any_call(
        ANY,
        page.components[2].component_id,
        component_to_dict(page.components[2], group_id="group_id_1"),
    )
    assert update_mock.call_count == 3


def test_delete_component(mocker):
    """
    Test if deletion is triggerd for a component that does not exist
    anymore in app-interface, but is still known to the State and to
    the status page.
    """
    fixture_name = "test_delete_component.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    delete_mock = mocker.patch.object(
        AtlassianStatusPage, "delete_component", autospec=True
    )
    delete_mock.return_value = None
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )

    page = get_page_fixtures(fixture_name)[0]
    state = get_state_fixture(fixture_name)

    page.reconcile(False, state)

    delete_mock.assert_called_with(ANY, False, "comp_id_1")
    assert delete_mock.call_count == 1


def test_group_exists(mocker):
    """
    Test if the creation logic is yielding an exception when a group is
    referenced, that does not exist.
    """
    fixture_name = "test_group_does_not_exist.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    vault_mock = mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )
    vault_mock.return_value = {"token": "token"}
    page = get_page_fixtures(fixture_name)[0]
    dry_run = True

    with pytest.raises(ValueError) as ex:
        page.reconcile(dry_run, StateStub())
    assert re.match(r"^Group.*does not exist$", str(ex.value))


def test_state_management_on_fetch(mocker):
    """
    Test if state management correctly relates component ids with
    components declared in desired state.
    """
    fixture_name = "test_state_management_on_fetch.yaml"
    apply_mock = mocker.patch.object(
        AtlassianStatusPage, "apply_component", autospec=True
    )
    apply_mock.return_value = None
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = []
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )

    page = get_page_fixtures(fixture_name)[0]
    page.reconcile(True, get_state_fixture(fixture_name))

    for c in page.components:
        if c.name == "comp_1":
            assert c.component_id == "comp_id_1"
        elif c.name == "comp_2":
            assert c.component_id is None


def test_state_management_on_bind(mocker):
    """
    Test if state management correctly binds components with their
    corresponding id on the status page.
    """
    fixture_name = "test_state_management_on_bind.yaml"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = get_atlassian_component_fixtures(fixture_name, "page_1")
    mocker.patch.object(
        VaultSecretRef, "_resolve_secret", new_callable=stub_resolve_secret
    )
    state = StateStub()

    page = get_page_fixtures(fixture_name)[0]
    page.reconcile(False, state)

    assert page.components[0].component_id == "comp_id_1"
    assert state.get_all("")["comp_1"] == "comp_id_1"


def test_dry_run_on_create(mocker):
    _exec_dry_run_test_on_create(mocker, True)


def test_no_dry_run_on_create(mocker):
    _exec_dry_run_test_on_create(mocker, False)


def _exec_dry_run_test_on_create(mocker, dry_run):
    create_mock = mocker.patch.object(
        AtlassianStatusPage, "_create_component", autospec=True
    )
    create_mock.return_value = "id"
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = []
    provider = AtlassianStatusPage(
        page_id="page_id", api_url="https://a.com", token="token"
    )

    component = StatusComponent(name="comp_1", displayName="comp_1", groupName=None)
    provider.apply_component(dry_run, component)

    if dry_run:
        create_mock.assert_not_called()
    else:
        create_mock.assert_called()


def test_dry_run_on_update(mocker):
    _exec_dry_run_test_on_update(mocker, True)


def test_no_dry_run_on_update(mocker):
    _exec_dry_run_test_on_update(mocker, False)


def _exec_dry_run_test_on_update(mocker, dry_run):
    update_mock = mocker.patch.object(
        AtlassianStatusPage, "_update_component", autospec=True
    )
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = [
        AtlassianComponent(
            id="comp_id_1",
            name="comp_1",
            description="old description",
            position=1,
            status="ok",
        )
    ]
    provider = AtlassianStatusPage(
        page_id="page_id", api_url="https://a.com", token="token"
    )
    provider.rebuild_state()

    component = StatusComponent(name="comp_1", displayName="comp_1", groupName=None)
    provider.apply_component(dry_run, component)

    if dry_run:
        update_mock.assert_not_called()
    else:
        update_mock.assert_called()


def test_no_status_management_provider():
    """
    status page component without or with empty status section
    """

    fixture_name = "test_no_status_management.yaml"
    page = get_page_fixtures(fixture_name)[0]

    for component in page.components:
        assert not component.status_management_enabled()


def test_no_desired_status_when_no_management_enabled():
    """
    test if desired status is none when no status management is enabled
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config = []

    assert not component.status_management_enabled()
    assert component.desired_component_status() is None


def test_atlassian_component_status_update(mocker):
    update_mock = mocker.patch.object(
        AtlassianStatusPage, "_update_component", autospec=True
    )
    fetch_mock = mocker.patch.object(
        AtlassianStatusPage, "_fetch_components", autospec=True
    )
    fetch_mock.return_value = [
        AtlassianComponent(
            id="comp_id_1",
            name="comp_1",
            description="old description",
            position=1,
            status="operational",
        )
    ]
    provider = AtlassianStatusPage(
        page_id="page_id", api_url="https://a.com", token="token"
    )
    provider.rebuild_state()

    status_config = StatusPageComponentStatusProvider(
        provider="manual",
        manual=StatusPageComponentStatusProviderManualConfig(
            componentStatus="under_maintenance"
        ),
    )

    component = StatusComponent(
        name="comp_1", displayName="comp_1", groupName=None, status=[status_config]
    )
    provider.apply_component(False, component)

    update_mock.assert_called_with(
        ANY, "comp_id_1", component_to_dict(component, status="under_maintenance")
    )


def test_manual_status_management_provider():
    """
    test if status management is detected
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]

    assert component.status_management_enabled()
    assert component.desired_component_status() == "under_maintenance"


def test_manual_status_management_provider_from_active():
    """
    test if status page component management is
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.start = datetime.now(timezone.utc) - timedelta(
        hours=1
    )

    assert component.desired_component_status() == "under_maintenance"


def test_manual_status_management_provider_from_inactive():
    """
    test if status page component management is
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.start = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    assert component.desired_component_status() == "operational"


def test_manual_status_management_provider_until_active():
    """
    test if status page component management is honoring end the the future
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.end = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    assert component.desired_component_status() == "under_maintenance"


def test_manual_status_management_provider_until_inactive():
    """
    test if status page component management is honoring end date in the past
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.end = datetime.now(timezone.utc) - timedelta(
        hours=1
    )

    assert component.desired_component_status() == "operational"


def test_manual_status_management_provider_from_until_active():
    """
    test if status page component management is honoring start and end date
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.start = datetime.now(timezone.utc) - timedelta(
        hours=1
    )
    component.status_config[0].manual.end = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    assert component.desired_component_status() == "under_maintenance"


def test_manual_status_management_provider_invalid_timerange():
    """
    test for invalid timerange: end before start
    """

    fixture_name = "test_status_management_manual.yaml"
    page = get_page_fixtures(fixture_name)[0]
    component = page.components[0]
    component.status_config[0].manual.start = datetime.now(timezone.utc) + timedelta(
        hours=1
    )
    component.status_config[0].manual.end = datetime.now(timezone.utc) - timedelta(
        hours=1
    )

    with pytest.raises(ValueError):
        component.desired_component_status()
