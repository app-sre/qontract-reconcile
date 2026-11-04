from typing import TYPE_CHECKING, Any

import pytest

from reconcile.test.runtime import (
    demo_integration,
    demo_integration_early_exit,
    demo_integration_no_name,
    demo_integration_no_run_func,
    demo_integration_shard_config,
)
from reconcile.utils.constants import REQUEST_TIMEOUT
from reconcile.utils.runtime.integration import (
    ModuleArgsKwargsRunParams,
    ModuleBasedQontractReconcileIntegration,
    setup_qontract_api_client,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_module_integration_no_name() -> None:
    """
    an integration with no QONTRACT_INTEGRATION name variable
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(
            ModuleArgsKwargsRunParams(module=demo_integration_no_name)
        )


def test_module_integration_no_run_func() -> None:
    """
    an integration with no run function
    """
    with pytest.raises(NotImplementedError):
        ModuleBasedQontractReconcileIntegration(
            ModuleArgsKwargsRunParams(module=demo_integration_no_run_func)
        )


def test_module_integration_run() -> None:
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


def test_demo_integration_no_early_exit_desired_state() -> None:
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(module=demo_integration, some_arg=1)
    )
    assert not integration.get_early_exit_desired_state()


def test_demo_integration_early_exit_desired_state() -> None:
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(
            demo_integration_early_exit, "arg", some_kw_arg="kwarg"
        )
    )
    data = integration.get_early_exit_desired_state()

    assert data == {"args": ("arg",), "kwargs": {"some_kw_arg": "kwarg"}}


def test_demo_integration_no_shard_config() -> None:
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(module=demo_integration, some_arg=1)
    )
    assert not integration.get_desired_state_shard_config()


def test_demo_integration_shard_config() -> None:
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
def test_demo_integration_params_have_shard_info(
    kwargs: Any, expected_result: bool
) -> None:
    integration = ModuleBasedQontractReconcileIntegration(
        ModuleArgsKwargsRunParams(
            demo_integration_shard_config,
            **kwargs,
        )
    )
    assert integration.params_have_shard_info() == expected_result


def test_setup_qontract_api_client_gives_sync_client_a_finite_timeout(
    mocker: MockerFixture,
) -> None:
    """The async client keeps an unbounded timeout (long blocking GETs), but the
    sync client used by fire-and-forget reconcile calls must not hang forever."""
    setup_qontract_api_client.cache_clear()
    mocker.patch(
        "reconcile.utils.runtime.integration.get_config",
        return_value={"qontract-api": {"server": "https://qontract-api.example.com"}},
    )
    mock_async_client = mocker.patch(
        "reconcile.utils.runtime.integration.qontract_api_client"
    )
    mock_sync_client = mocker.patch(
        "reconcile.utils.runtime.integration.qontract_api_sync_client"
    )

    setup_qontract_api_client()

    async_config = mock_async_client.configure.call_args.kwargs["config"]
    sync_config = mock_sync_client.configure.call_args.kwargs["config"]
    assert async_config.timeout is None
    assert sync_config.timeout == REQUEST_TIMEOUT

    setup_qontract_api_client.cache_clear()
