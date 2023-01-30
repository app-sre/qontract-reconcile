import pytest

from reconcile.test.runtime import (
    demo_integration,
    demo_integration_early_exit,
    demo_integration_no_name,
    demo_integration_no_run_func,
    demo_integration_shard_config,
)
from reconcile.utils.runtime.integration import ModuleBasedQontractReconcileIntegration


def test_module_integration_no_name():
    """
    an integration with no QONTRACT_INTEGRATION name variable
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(demo_integration_no_name)


def test_module_integration_no_run_func():
    """
    an integration with no run function
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(demo_integration_no_run_func)


def test_module_integration_run():
    demo_integration.run_calls = []
    integration = ModuleBasedQontractReconcileIntegration(demo_integration)
    integration.run(dry_run=True, some_arg=1)

    assert {
        "some_arg": 1,
        "dry_run": True,
    } in demo_integration.run_calls
    demo_integration.run_calls = []


def test_demo_integration_no_early_exit_desired_state():
    integration = ModuleBasedQontractReconcileIntegration(demo_integration)
    assert not integration.get_early_exit_desired_state(some_arg=1)


def test_demo_integration_early_exit_desired_state():
    integration = ModuleBasedQontractReconcileIntegration(demo_integration_early_exit)
    data = integration.get_early_exit_desired_state("arg", some_kw_arg="kwarg")

    assert data == {"args": ("arg",), "kwargs": {"some_kw_arg": "kwarg"}}


def test_demo_integration_no_shard_config():
    integration = ModuleBasedQontractReconcileIntegration(demo_integration)
    assert not integration.get_desired_state_shard_config()


def test_demo_integration_shard_config():
    integration = ModuleBasedQontractReconcileIntegration(demo_integration_shard_config)
    assert integration.get_desired_state_shard_config()


def test_demo_integration_kwargs_have_shard_info():
    integration = ModuleBasedQontractReconcileIntegration(demo_integration_shard_config)
    assert integration.kwargs_have_shard_info(
        **{demo_integration_shard_config.SHARD_ARG_NAME: "shard1"}
    )

    assert not integration.kwargs_have_shard_info(
        **{demo_integration_shard_config.SHARD_ARG_NAME: None}
    )

    assert not integration.kwargs_have_shard_info(**{})
