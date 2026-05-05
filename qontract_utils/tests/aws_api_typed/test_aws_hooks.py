from __future__ import annotations

import time
from unittest.mock import patch

from qontract_utils.aws_api_typed import _hooks  # noqa: PLC2701
from qontract_utils.aws_api_typed._hooks import AWSApiCallContext  # noqa: PLC2701


def test_context_creation() -> None:
    ctx = AWSApiCallContext(method="assume_role", service="sts")
    assert ctx.method == "assume_role"
    assert ctx.service == "sts"


def test_metrics_hook_increments_counter() -> None:
    ctx = AWSApiCallContext(method="create_account", service="organizations")
    before = _hooks.aws_request.labels("create_account", "organizations")._value.get()
    _hooks._metrics_hook(ctx)
    after = _hooks.aws_request.labels("create_account", "organizations")._value.get()
    assert after == before + 1


def test_latency_tracking() -> None:
    ctx = AWSApiCallContext(method="assume_role", service="sts")
    _hooks._latency_start_hook(ctx)
    assert len(_hooks._latency_tracker.get()) == 1
    _hooks._latency_end_hook(ctx)
    assert len(_hooks._latency_tracker.get()) == 0


def test_latency_nested_calls() -> None:
    ctx_outer = AWSApiCallContext(method="move_account", service="organizations")
    ctx_inner = AWSApiCallContext(method="get_ou", service="organizations")
    _hooks._latency_start_hook(ctx_outer)
    _hooks._latency_start_hook(ctx_inner)
    assert len(_hooks._latency_tracker.get()) == 2
    _hooks._latency_end_hook(ctx_inner)
    assert len(_hooks._latency_tracker.get()) == 1
    _hooks._latency_end_hook(ctx_outer)
    assert len(_hooks._latency_tracker.get()) == 0


def test_latency_end_hook_observes_duration() -> None:
    ctx = AWSApiCallContext(method="test_duration", service="sts")
    _hooks._latency_start_hook(ctx)
    with patch.object(time, "perf_counter", return_value=time.perf_counter() + 0.5):
        _hooks._latency_end_hook(ctx)
    assert _hooks.aws_request_duration.labels("test_duration", "sts")._sum.get() > 0


def test_request_log_hook() -> None:
    ctx = AWSApiCallContext(method="describe_account", service="organizations")
    _hooks._request_log_hook(ctx)


def test_default_hooks_structure() -> None:
    hooks = _hooks.AWS_DEFAULT_HOOKS
    assert len(hooks.pre_hooks) == 3
    assert len(hooks.post_hooks) == 1
    assert hooks.retry_config is None
    assert _hooks._metrics_hook in hooks.pre_hooks
    assert _hooks._request_log_hook in hooks.pre_hooks
    assert _hooks._latency_start_hook in hooks.pre_hooks
    assert _hooks._latency_end_hook in hooks.post_hooks
