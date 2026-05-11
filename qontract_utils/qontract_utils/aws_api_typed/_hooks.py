"""Shared hooks infrastructure for AWS API typed clients."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass

import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

aws_request = Counter(
    "qontract_reconcile_external_api_aws_requests_total",
    "Total number of AWS API requests",
    ["method", "service"],
)

aws_request_duration = Histogram(
    "qontract_reconcile_external_api_aws_request_duration_seconds",
    "AWS API request duration in seconds",
    ["method", "service"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


@dataclass(frozen=True)
class AWSApiCallContext:
    """Context information passed to API call hooks."""

    method: str
    service: str


def _metrics_hook(context: AWSApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    aws_request.labels(context.method, context.service).inc()


def _latency_start_hook(_context: AWSApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: AWSApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    aws_request_duration.labels(context.method, context.service).observe(duration)


def _request_log_hook(context: AWSApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug(
        "AWS API request",
        method=context.method,
        service=context.service,
    )


AWS_DEFAULT_HOOKS = Hooks(
    pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
    post_hooks=[_latency_end_hook],
)
