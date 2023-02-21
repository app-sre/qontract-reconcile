import pytest
from pytest_mock import MockerFixture

from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.statuspage.page import StatusComponent
from reconcile.statuspage.status import ManualStatusProvider

"""
About the `atlassian_page` fixture:
* it has three components, but only two are bound to a statuspage components
 * the components id-1 (component-1) and id-2 (component-2) are bound to the app-interface components
    ai-component-1 and ai-component-2 respectively
 * the third component component-3 is not bound to any app-interface component
"""


def test_atlassian_page_read_component_bindings(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    Tests that the component binding state is correctly initialized.
    """
    assert atlassian_page.has_component_binding_for("ai-component-1")
    assert atlassian_page.has_component_binding_for("ai-component-2")
    assert not atlassian_page.has_component_binding_for("some-other-component")


def test_atlassian_page_lookup_bound_component(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    Test that a bound component can be found by its app-interface name.

    The fixture contains a component named component-1 with id-1. The binding
    state contains a binding of this id-1 to an app-interface name ai-component-1.
    Therefore the lookup function must resolve the app-interface component
    ai-component-1 to the component with id-1.
    """
    desired_state_component = StatusComponent(
        name="ai-component-1",
        display_name=(
            "Some component display name that does"
            "not match a component name on the page"
        ),
        description=None,
        group_name=None,
        status_provider_configs=[],
    )

    current_component, bound = atlassian_page.lookup_component(desired_state_component)
    assert bound
    assert current_component
    assert current_component.id == "id-1"
    assert current_component.name == "component-1"


def test_atlassian_page_lookup_by_display_name(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    Test that an unbound component can still be looked up if its name matches
    the display name of an app-interface component.

    The fixtures contains an unbound component named component-3 with id-3.
    Therefore, we should successfully look up this component if we provide
    a desired state component with a displayname component-3.
    """
    desired_state_component = StatusComponent(
        name="ai-component-3",
        display_name=("component-3"),
        description=None,
        group_name=None,
        status_provider_configs=[],
    )

    current_component, bound = atlassian_page.lookup_component(desired_state_component)
    assert not bound
    assert current_component
    assert current_component.id == "id-3"
    assert current_component.name == "component-3"


def test_atlassian_page_fail_lookup_for_already_bound_component(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    Test that a lookup by display name fails if the respective component is
    already bound.

    The fixture contains a binding of the component named component-2 with id-2
    to the app-interface. Therefore a lookup by display name from another component
    must be unsuccessful.
    """
    desired_state_component = StatusComponent(
        name="ai-component-3",  # ai-component-3 is not bound
        display_name=(
            "component-2"
        ),  # but the component with this display name is bound
        description=None,
        group_name=None,
        status_provider_configs=[],
    )

    component, bound = atlassian_page.lookup_component(desired_state_component)
    assert not component
    assert not bound


def test_atlassian_provider_get_current_page(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    Tests the construction of a StatusPage object from the current state of
    the Atlassian page.
    """
    page = atlassian_page.get_current_page()
    assert page.name == "page"
    # only the two bound components should be present
    assert len(page.components) == 2
    # only one component has a group
    assert {c.group_name for c in page.components if c.group_name} == {"group-1"}
    # test that the status of the components were correctly translated
    assert {c.desired_component_status() for c in page.components} == {
        "operational",
        "under_maintenance",
    }


@pytest.mark.parametrize("dry_run", [True, False])
def test_atlassian_page_bind_on_apply(
    dry_run: bool, atlassian_page: AtlassianStatusPageProvider
):
    """
    Tests that a component is bound to the page when it is applied.
    """
    desired_state_component = StatusComponent(
        name="ai-component-3",
        display_name="component-3",
        description=None,
        group_name=None,
        status_provider_configs=[],
    )

    assert not atlassian_page.has_component_binding_for("ai-component-3")
    atlassian_page.apply_component(dry_run, desired_state_component)
    if dry_run:
        # if the apply is a dry-run, the binding should not be created
        assert not atlassian_page.has_component_binding_for("ai-component-3")
    else:
        # if the apply is not a dry-run, the binding should be created
        assert atlassian_page.has_component_binding_for("ai-component-3")


def test_atlassian_page_should_apply_on_status_update(
    atlassian_page: AtlassianStatusPageProvider,
):
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore
    desired.status_provider_configs = [
        ManualStatusProvider(component_status="another-state")
    ]

    assert atlassian_page.should_apply(desired, current)


def test_atlassian_page_should_apply_on_missing_group(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    The atlassian provider does not create missing groups. So a component
    validation should fail when a missing group is referenced.
    """
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore
    desired.group_name = "some-non-existing-group"

    with pytest.raises(ValueError):
        atlassian_page.should_apply(desired, current)


def test_atlassian_page_should_apply_on_moving_outside_group(
    atlassian_page: AtlassianStatusPageProvider,
):
    """
    The atlassian provider does not support moving components out of a group.
    """
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore
    desired.group_name = None

    with pytest.raises(ValueError):
        atlassian_page.should_apply(desired, current)


def test_atlassian_page_should_apply_on_display_name_update(
    atlassian_page: AtlassianStatusPageProvider,
):
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore
    desired.display_name = "some other display name"

    assert atlassian_page.should_apply(desired, current)


def test_atlassian_page_should_apply_on_no_update(
    atlassian_page: AtlassianStatusPageProvider,
):
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore

    assert not atlassian_page.should_apply(desired, current)


@pytest.mark.parametrize("dry_run", [True, False])
def test_atlassian_page_apply_component_update(
    dry_run: bool, atlassian_page: AtlassianStatusPageProvider, mocker: MockerFixture
):
    component_id = "id-1"
    current = atlassian_page.get_raw_component_by_id(component_id)
    assert current
    desired = atlassian_page.get_component_by_id(component_id).copy(deep=True)  # type: ignore
    desired.description = "some other description"

    update_component_mock = mocker.patch.object(atlassian_page._api, "update_component")

    atlassian_page.apply_component(dry_run, desired)

    if dry_run:
        update_component_mock.assert_not_called()
    else:
        update_component_mock.assert_called_with(
            component_id,
            {
                "name": desired.display_name,
                "description": desired.description,
                "group_id": current.group_id,
                "status": desired.desired_component_status(),
            },
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_atlassian_page_delete_component(
    dry_run: bool, atlassian_page: AtlassianStatusPageProvider, mocker: MockerFixture
):
    component_to_delete = "ai-component-1"
    component_id_to_delete = "id-1"
    delete_component_mock = mocker.patch.object(atlassian_page._api, "delete_component")

    # precheck
    assert atlassian_page.has_component_binding_for(component_to_delete)
    assert atlassian_page.get_component_by_id(component_id_to_delete)

    # delete
    atlassian_page.delete_component(dry_run, component_to_delete)

    if dry_run:
        delete_component_mock.assert_not_called()
        assert atlassian_page.has_component_binding_for(component_to_delete)
        assert atlassian_page.get_component_by_id(component_id_to_delete)
    else:
        delete_component_mock.assert_called_with("id-1")
        assert not atlassian_page.has_component_binding_for(component_to_delete)
        assert not atlassian_page.get_component_by_id(component_id_to_delete)


def test_atlassian_page_dont_update_status_when_no_status_provider(
    atlassian_page: AtlassianStatusPageProvider,
):
    current = atlassian_page.get_raw_component_by_id("id-1")
    assert current
    current.status = "some-status"
    desired = atlassian_page.get_component_by_id("id-1").copy(deep=True)  # type: ignore
    desired.status_provider_configs = []

    assert not atlassian_page.should_apply(desired, current)
