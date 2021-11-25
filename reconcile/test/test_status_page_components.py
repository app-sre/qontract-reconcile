from unittest import TestCase
from unittest.mock import patch
from typing import Optional

from reconcile.status_page_components import (
  AtlassianComponent, AtlassianStatusPage, StatusComponent, StatusPage)
from reconcile.utils.vaultsecretref import VaultSecretRef
from .fixtures import Fixtures


fxt = Fixtures('statuspage')


def get_page_fixtures(path: str) -> list[StatusPage]:
    pages = fxt.get_anymarkup(path)["appInterface"]["pages"]
    return [StatusPage(**p) for p in pages]


def get_atlassian_component_fixtures(path: str, page_id: str) \
        -> list[AtlassianComponent]:
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

    def get_all(self, _):
        return self.state

    def add(self, key, value, force=False):
        self.state[key] = value

    def rm(self, key):
        del self.state[key]


def get_state_fixture(path: str) -> StateStub:
    return StateStub(fxt.get_anymarkup(path)["appInterface"]["state"])


def component_to_dict(component: StatusComponent,
                      group_id: Optional[str]) -> dict[str, Optional[str]]:
    data = dict(
        name=component.display_name,
        description=component.description,
    )
    if group_id:
        data["group_id"] = group_id
    return data


def stub_resolve_secret():
    def f(self):
        return {"token": "token"}
    return f


class TestReconcileLogic(TestCase):

    @staticmethod
    @patch.object(VaultSecretRef, '_resolve_secret',
                  new_callable=stub_resolve_secret)
    @patch.object(AtlassianStatusPage, '_create_component')
    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_create_component(fetch_mock, create_mock, vault_mock):
        """
        Test if the creation logic is called for a component missing on the
        status page.
        """
        fixture_name = "test_create_component.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        create_mock.return_value = None
        page = get_page_fixtures(fixture_name)[0]

        page.reconcile(False, StateStub())

        create_mock.assert_called_with(
            component_to_dict(page.components[0], "group_id_1")
        )

    @staticmethod
    @patch.object(VaultSecretRef, '_resolve_secret',
                  new_callable=stub_resolve_secret)
    @patch.object(StatusPage, '_bind_component')
    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_bind_component(fetch_mock, bind_mock, vault_mock):
        """
        Test if bind logic is called for a component that already exists on
        the status page but is not bound to the one in desired state.
        """
        fixture_name = "test_bind_component.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        page = get_page_fixtures(fixture_name)[0]
        state = StateStub()

        # execute bind logic through reconciling
        page.reconcile(False, state)

        # check if binding was called
        bind_mock.assert_called_with(False, page.components[0],
                                     "comp_id_1", state)

    @patch.object(VaultSecretRef, '_resolve_secret',
                  new_callable=stub_resolve_secret)
    @patch.object(AtlassianStatusPage, '_update_component')
    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_update_component(self, fetch_mock, update_mock, vault_mock):
        """
        Test if updates are triggered for components when their name, group
        or description changes. The fixture for this test includes three
        components, that need update for different reasons, and one component
        that is up to date.
        """
        fixture_name = "test_update_component.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        update_mock.return_value = None
        page = get_page_fixtures(fixture_name)[0]
        self.assertEqual(len(page.components), 4)

        page.reconcile(False, get_state_fixture(fixture_name))

        update_mock.assert_any_call(
            page.components[0].component_id,
            component_to_dict(page.components[0], "group_id_1"))
        update_mock.assert_any_call(
            page.components[1].component_id,
            component_to_dict(page.components[1], "group_id_1"))
        update_mock.assert_any_call(
            page.components[2].component_id,
            component_to_dict(page.components[2], "group_id_1"))
        self.assertEqual(update_mock.call_count, 3)

    @patch.object(VaultSecretRef, '_resolve_secret',
                  new_callable=stub_resolve_secret)
    @patch.object(AtlassianStatusPage, 'delete_component')
    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_delete_component(self, fetch_mock, delete_mock, vault_mock):
        """
        Test if deletion is triggerd for a component that does not exist
        anymore in app-interface, but is still known to the State and to
        the status page.
        """
        fixture_name = "test_delete_component.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        delete_mock.return_value = None
        page = get_page_fixtures(fixture_name)[0]
        state = get_state_fixture(fixture_name)

        page.reconcile(False, state)

        delete_mock.assert_called_with(False, "comp_id_1")
        self.assertEqual(delete_mock.call_count, 1)

    @patch.object(VaultSecretRef, '_resolve_secret',
                  new_callable=stub_resolve_secret)
    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_group_exists(self, fetch_mock, vault_mock):
        """
        Test if the creation logic is yielding an exception when a group is
        referenced, that does not exist.
        """
        fixture_name = "test_group_does_not_exist.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        vault_mock.return_value = {"token": "token"}
        page = get_page_fixtures(fixture_name)[0]
        dry_run = True

        with self.assertRaises(ValueError) as cm:
            page.reconcile(dry_run, StateStub())
        self.assertRegex(str(cm.exception), r"^Group.*does not exist$")


class TestComponentOrdering(TestCase):

    def test_place_component_in_empty_group(self):
        pass

    def test_place_component_in_group(self):
        pass

    def test_place_component_top_level(self):
        pass


@patch.object(VaultSecretRef, '_resolve_secret',
              new_callable=stub_resolve_secret)
class TestStateManagement(TestCase):

    @patch.object(AtlassianStatusPage, '_fetch_components')
    @patch.object(AtlassianStatusPage, 'apply_component')
    def test_state_management_on_fetch(self, apply_mock, fetch_mock,
                                       vault_mock):
        """
        Test if state management correctly relates component ids with
        components declared in desired state.
        """
        fixture_name = "test_state_management_on_fetch.yaml"
        apply_mock.return_value = None
        fetch_mock.return_value = []
        page = get_page_fixtures(fixture_name)[0]

        page.reconcile(True, get_state_fixture(fixture_name))

        for c in page.components:
            if c.name == "comp_1":
                self.assertEqual(c.component_id, "comp_id_1")
            elif c.name == "comp_2":
                self.assertIsNone(c.component_id)

    @patch.object(AtlassianStatusPage, '_fetch_components')
    def test_state_management_on_bind(self, fetch_mock, vault_mock):
        """
        Test if state management correctly binds components with their
        corresponding id on the status page.
        """
        fixture_name = "test_state_management_on_bind.yaml"
        fetch_mock.return_value = \
            get_atlassian_component_fixtures(fixture_name, "page_1")
        state = StateStub()
        page = get_page_fixtures(fixture_name)[0]

        page.reconcile(False, state)

        self.assertEqual(page.components[0].component_id, "comp_id_1")
        self.assertEqual(state.get_all("")["comp_1"], "comp_id_1")


class TestDryRunBehaviour(TestCase):

    @staticmethod
    @patch.object(AtlassianStatusPage, '_fetch_components')
    @patch.object(AtlassianStatusPage, "_create_component")
    def test_dry_run_on_create(create_mock, fetch_mock):
        TestDryRunBehaviour._exec_dry_run_test_on_create(True, create_mock,
                                                         fetch_mock)

    @staticmethod
    @patch.object(AtlassianStatusPage, '_fetch_components')
    @patch.object(AtlassianStatusPage, "_create_component")
    def test_no_dry_run_on_create(create_mock, fetch_mock):
        TestDryRunBehaviour._exec_dry_run_test_on_create(False, create_mock,
                                                         fetch_mock)

    @staticmethod
    def _exec_dry_run_test_on_create(dry_run, create_mock, fetch_mock):
        create_mock.create.return_value = "id"
        fetch_mock.return_value = []
        provider = AtlassianStatusPage(page_id="page_id",
                                       api_url="https://a.com",
                                       token="token")

        component = StatusComponent(name="comp_1", displayName="comp_1",
                                    groupName=None)
        provider.apply_component(dry_run, component)

        if dry_run:
            create_mock.assert_not_called()
        else:
            create_mock.assert_called()

    @staticmethod
    @patch.object(AtlassianStatusPage, '_fetch_components')
    @patch.object(AtlassianStatusPage, "_update_component")
    def test_dry_run_on_update(update_mock, fetch_mock):
        TestDryRunBehaviour._exec_dry_run_test_on_update(True, update_mock,
                                                         fetch_mock)

    @staticmethod
    @patch.object(AtlassianStatusPage, '_fetch_components')
    @patch.object(AtlassianStatusPage, "_update_component")
    def test_no_dry_run_on_update(update_mock, fetch_mock):
        TestDryRunBehaviour._exec_dry_run_test_on_update(False, update_mock,
                                                         fetch_mock)

    @staticmethod
    def _exec_dry_run_test_on_update(dry_run, update_mock, fetch_mock):
        fetch_mock.return_value = [
            AtlassianComponent(
                id="comp_id_1",
                name="comp_1",
                description="old description",
                position=1,
                status="ok"
            )
        ]
        provider = AtlassianStatusPage(page_id="page_id",
                                       api_url="https://a.com",
                                       token="token")

        component = StatusComponent(name="comp_1", displayName="comp_1",
                                    groupName=None)
        provider.apply_component(dry_run, component)

        if dry_run:
            update_mock.assert_not_called()
        else:
            update_mock.assert_called()
