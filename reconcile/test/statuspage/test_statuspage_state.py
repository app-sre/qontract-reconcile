from unittest.mock import MagicMock

import pytest

from reconcile.statuspage.state import S3ComponentBindingState
from reconcile.utils.state import State


@pytest.fixture
def state_mock() -> State:
    state = MagicMock(spec=State)
    state.get_all = MagicMock(
        return_value={"ai-component-1": "id-1", "ai-component-2": "id-2"}
    )
    return state


def test_s3_component_binding_state(state_mock: State):
    binding_state = S3ComponentBindingState(state_mock)
    assert binding_state.get_id_for_component_name("ai-component-1") == "id-1"
    assert binding_state.get_id_for_component_name("ai-component-2") == "id-2"
    assert binding_state.get_name_for_component_id("id-1") == "ai-component-1"
    assert binding_state.get_name_for_component_id("id-2") == "ai-component-2"


def test_s3_component_binding_state_bind(state_mock: State):
    binding_state = S3ComponentBindingState(state_mock)
    binding_state.bind_component("ai-component-3", "id-3")
    state_mock.add.assert_called_once_with("ai-component-3", "id-3", force=True)  # type: ignore


def test_s3_component_binding_state_forget(state_mock: State):
    binding_state = S3ComponentBindingState(state_mock)
    binding_state.forget_component("ai-component-3")
    state_mock.rm.assert_called_once_with("ai-component-3")  # type: ignore
