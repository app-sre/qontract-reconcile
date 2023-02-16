from typing import Any

import pytest

from reconcile.test.runtime import (
    demo_integration,
    demo_integration_early_exit,
    demo_integration_no_name,
    demo_integration_no_run_func,
    demo_integration_shard_config,
)
from reconcile.utils.runtime.integration import (
    ModuleArgsKwargsRunParams,
    ModuleBasedQontractReconcileIntegration,
)


def test_module_integration_no_name():
    """
    an integration with no QONTRACT_INTEGRATION name variable
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(
            ModuleArgsKwargsRunParams(module=demo_integration_no_name)
        )


def test_module_integration_no_run_func():
    """
    an integration with no run function
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(
            ModuleArgsKwargsRunParams(module=demo_integration_no_run_func)
        )


def test_module_integration_run():
    demo_integration.run_calls = []
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(module=demo_integration, some_arg=1)
    )
    integration.run(dry_run=True)

    assert {
        "some_arg": 1,
        "dry_run": True,
    } in demo_integration.run_calls
    demo_integration.run_calls = []


def test_demo_integration_no_early_exit_desired_state():
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(module=demo_integration, some_arg=1)
    )
    assert not integration.get_early_exit_desired_state()


def test_demo_integration_early_exit_desired_state():
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(
            demo_integration_early_exit, "arg", some_kw_arg="kwarg"
        )
    )
    data = integration.get_early_exit_desired_state()

    assert data == {"args": ("arg",), "kwargs": {"some_kw_arg": "kwarg"}}


def test_demo_integration_no_shard_config():
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(module=demo_integration, some_arg=1)
    )
    assert not integration.get_desired_state_shard_config()


def test_demo_integration_shard_config():
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(demo_integration_shard_config)
    )
    assert integration.get_desired_state_shard_config()


@pytest.mark.parametrize(
    "kwargs,expected_result",
    [
        # no comparison bundle available, so no early exit and no sharding
        ({demo_integration_shard_config.SHARD_ARG_NAME: "shard1"}, True),
        ({demo_integration_shard_config.SHARD_ARG_NAME: ["shard1"]}, True),
        ({demo_integration_shard_config.SHARD_ARG_NAME: None}, False),
        ({demo_integration_shard_config.SHARD_ARG_NAME: ()}, False),
        ({demo_integration_shard_config.SHARD_ARG_NAME: []}, False),
        ({}, False),
    ],
)
def test_demo_integration_params_have_shard_info(kwargs: Any, expected_result: bool):
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(
            demo_integration_shard_config,
            **kwargs,
        )
    )
    assert integration.params_have_shard_info() == expected_result
