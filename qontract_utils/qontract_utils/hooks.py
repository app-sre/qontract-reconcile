import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import stamina

# Type matching stamina.retry() signature exactly
type OnType = (
    type[Exception]
    | tuple[type[Exception], ...]
    | Callable[[Exception], bool | float | timedelta]
)


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behavior using stamina library.

    All parameters match stamina.retry() signature exactly.
    See: https://stamina.hynek.me/en/stable/api.html

    Args:
        on: Exception type(s) to retry on, or callable for custom backoff logic.
            - Type or tuple: Retry on these exception types
            - Callable: Custom decision function (return False=don't retry, True=retry,
              float/timedelta=retry with custom wait time)
        attempts: Max retry attempts (default: 10)
        timeout: Max total time in seconds (default: 45.0)
        wait_initial: Initial wait in seconds (default: 0.1)
        wait_max: Max wait between retries in seconds (default: 5.0)
        wait_jitter: Jitter in seconds (default: 1.0)
        wait_exp_base: Exponential backoff base (default: 2)

    Examples:
        >>> # Retry network errors up to 5 times with 30s timeout
        >>> config = RetryConfig(on=httpx.HTTPError, attempts=5, timeout=30.0)

        >>> # Custom backoff logic (only retry on 5xx errors)
        >>> def should_retry(exc: Exception) -> bool:
        ...     if isinstance(exc, HTTPError):
        ...         return 500 <= exc.status_code < 600
        ...     return False
        >>> config = RetryConfig(on=should_retry, attempts=5)
    """

    on: OnType
    attempts: int = 10
    timeout: float = 45.0
    wait_initial: float = 0.1
    wait_max: float = 5.0
    wait_jitter: float = 1.0
    wait_exp_base: int = 2


# Public constant for clients to explicitly disable retry
NO_RETRY_CONFIG = RetryConfig(on=Exception, attempts=1)
DEFAULT_RETRY_CONFIG = RetryConfig(on=Exception)


class invoke_with_hooks:  # noqa: N801 - lowercase for decorator API aesthetics
    """Method decorator for API calls with hook and retry support.

    Args:
        context_factory: Callable that creates context object from method arguments.
                        Signature: (instance, *args, **kwargs) -> Context
        retry_config: Optional retry configuration to override instance._retry_config.
                     Use NO_RETRY_CONFIG to disable retries for this specific method.

    Examples:
        >>> class MyApi:
        ...     @invoke_with_hooks(
        ...         lambda self: MyApiCallContext(
        ...             method="users.list",
        ...             verb="GET",
        ...             workspace=self.workspace_name
        ...         )
        ...     )
        ...     def users_list(self):
        ...         return self._client.user_list()
        ...
        ...     # Disable retry for specific method
        ...     @invoke_with_hooks(
        ...         lambda self: MyApiCallContext(method="test", verb="GET"),
        ...         retry_config=NO_RETRY_CONFIG
        ...     )
        ...     def test_connection(self) -> bool:
        ...         return self._sc.test_connection()
    """

    def __init__(
        self,
        context_factory: Callable[..., Any],
        retry_config: RetryConfig | None = None,
    ) -> None:
        self.context_factory = context_factory
        self.retry_config = retry_config

    def __call__(self, func: Callable[..., Any]) -> Any:
        """Wrap function with InvokeWithHooksMethod descriptor."""
        return InvokeWithHooksMethod(func, self.context_factory, self.retry_config)


class InvokeWithHooksMethod:
    """Descriptor that wraps methods with hooks and retry support.

    Retrieves hook configuration from the instance (_retry_config, _pre_hooks, etc.)
    and executes the method with stamina.retry_context.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        context_factory: Callable[..., Any],
        retry_config_override: RetryConfig | None = None,
    ) -> None:
        self.func = func
        self.context_factory = context_factory
        self.retry_config_override = retry_config_override
        # Copy metadata from the wrapped function
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__
        self.__module__ = func.__module__
        self.__qualname__ = func.__qualname__
        self.__annotations__ = func.__annotations__

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        """Descriptor protocol - binds method to instance."""
        if instance is None:
            return self

        @functools.wraps(self.func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get hook config from instance (or use override from decorator)
            retry_config = (
                self.retry_config_override
                or getattr(instance, "_retry_config", None)
                or NO_RETRY_CONFIG
            )
            pre_hooks = getattr(instance, "_pre_hooks", [])
            post_hooks = getattr(instance, "_post_hooks", [])
            error_hooks = getattr(instance, "_error_hooks", [])
            retry_hooks = getattr(instance, "_retry_hooks", [])

            # Create context (only pass instance to context_factory)
            context = self.context_factory(instance)

            # Pre-hooks (once before retry)
            for hook in pre_hooks:
                hook(context)

            try:
                # Create meaningful name for stamina instrumentation
                callable_name = f"{instance.__class__.__name__}.{self.func.__name__}"

                # Retry loop with proper callable identification
                retry_ctx = stamina.retry_context(
                    on=retry_config.on,
                    attempts=retry_config.attempts,
                    timeout=retry_config.timeout,
                    wait_initial=retry_config.wait_initial,
                    wait_max=retry_config.wait_max,
                    wait_jitter=retry_config.wait_jitter,
                    wait_exp_base=retry_config.wait_exp_base,
                )

                for attempt in retry_ctx.with_name(callable_name, (), {}):
                    with attempt:
                        # Retry hooks (not on first attempt)
                        if attempt.num > 1:
                            for retry_hook in retry_hooks:
                                retry_hook(context, attempt.num)

                        # Execute method - no yield, just return!
                        return self.func(instance, *args, **kwargs)
            except:
                # Error hooks
                for hook in error_hooks:
                    hook(context)
                raise
            finally:
                # Post hooks
                for hook in post_hooks:
                    hook(context)

        return wrapper
