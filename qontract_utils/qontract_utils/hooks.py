import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Self

import stamina
from pydantic import BaseModel, Field

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


class Hooks(BaseModel, frozen=True):
    """Hook configuration for API clients.

    Supports two usage patterns:

    1. **Decorator Pattern** (recommended for API client methods):
       Use @invoke_with_hooks decorator on methods (class instance or static).

    2. **Direct Invocation** (for standalone functions or one-off calls):
       Use hooks.invoke() or hooks.with_context().invoke() for direct execution.

    Examples:
        Decorator pattern (recommended for API clients):
        >>> class MyApi:
        ...     def __init__(self, hooks: Hooks | None = None):
        ...         _hooks = hooks or Hooks()
        ...         self._hooks = Hooks(
        ...             pre_hooks=[_metrics_hook, *_hooks.pre_hooks],
        ...             post_hooks=_hooks.post_hooks,
        ...             error_hooks=_hooks.error_hooks,
        ...             retry_hooks=_hooks.retry_hooks,
        ...             retry_config=_hooks.retry_config,
        ...         )
        ...
        ...     @invoke_with_hooks(lambda self: MyContext(method="test"))
        ...     def test(self) -> str:
        ...         return "result"

        Direct invocation without context:
        >>> def my_function(x: int) -> int:
        ...     return x * 2
        >>> hooks = Hooks(pre_hooks=[logging_hook], retry_config=NO_RETRY_CONFIG)
        >>> result = hooks.invoke(my_function, 5)
        >>> # Pre-hooks run with empty dict context, then my_function(5) executes

        Direct invocation with context:
        >>> @dataclass(frozen=True)
        ... class RequestContext:
        ...     method: str
        ...     endpoint: str
        >>> def make_request(url: str) -> dict:
        ...     return {"status": 200}
        >>> hooks = Hooks(pre_hooks=[rate_limit_hook], retry_config=NO_RETRY_CONFIG)
        >>> context = RequestContext(method="GET", endpoint="/users")
        >>> result = hooks.with_context(context).invoke(make_request, "https://api.example.com/users")
        >>> # Pre-hooks run with RequestContext, then make_request() executes
    """

    pre_hooks: list[Callable[..., None]] = Field(default_factory=list)
    post_hooks: list[Callable[..., None]] = Field(default_factory=list)
    error_hooks: list[Callable[..., None]] = Field(default_factory=list)
    retry_hooks: list[Callable[..., None]] = Field(default_factory=list)
    retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG

    def with_context(self, context: Any) -> Self:
        """Set context for hook execution.

        Args:
            context: Context object to pass to hooks. Can be any type (dict, dataclass, etc.)

        Returns:
            Self for method chaining with invoke()

        Examples:
            >>> context = {"method": "GET", "url": "/users"}
            >>> hooks.with_context(context).invoke(fetch_users)
        """
        self._context = context
        return self

    def invoke(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke a function with hook execution.

        Executes pre-hooks, the function, post-hooks, and handles errors with error-hooks.
        If with_context() was called, hooks receive that context; otherwise empty dict.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Return value from func

        Examples:
            Without context:
            >>> hooks = Hooks(pre_hooks=[log_hook])
            >>> result = hooks.invoke(my_function, "arg1", kwarg="value")

            With context:
            >>> ctx = {"method": "POST", "endpoint": "/users"}
            >>> result = hooks.with_context(ctx).invoke(create_user, user_data)
        """
        context = getattr(self, "_context", None)
        wrapper = _ExecutionWrapper()
        wrapper._hooks = self  # noqa: SLF001
        return InvokeWithHooksMethod(func, lambda _: context).__get__(wrapper)(
            *args, **kwargs
        )


class _ExecutionWrapper:
    """Internal wrapper class to bind InvokeWithHooksMethod descriptor."""

    _hooks: Hooks


class invoke_with_hooks:  # noqa: N801 - lowercase for decorator API aesthetics
    """Method decorator for API calls with hook and retry support.

    Args:
        context_factory: Callable that creates context object from method arguments.
                        Signature: (instance, *args, **kwargs) -> Context
        retry_config: Optional retry configuration to override instance._retry_config.
                     Use NO_RETRY_CONFIG to disable retries for this specific method.

    Examples:
        >>> class MyApi:
        ...     def __init__(self, ..., hooks: Hooks | None = None):
        ...         self._hooks = hooks

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
        context_factory: Callable[..., Any] | None = None,
        retry_config: RetryConfig | None = None,
        hooks: Hooks | None = None,
    ) -> None:
        self.context_factory = context_factory
        if retry_config is not None and hooks is not None:
            raise ValueError("Cannot specify both retry_config and hooks in decorator")
        self.retry_config = retry_config
        self.hooks = hooks

    def __call__(self, func: Callable[..., Any]) -> Any:
        """Wrap function with InvokeWithHooksMethod descriptor."""
        return InvokeWithHooksMethod(
            func, self.context_factory, self.retry_config, self.hooks
        )


class InvokeWithHooksMethod:
    """Descriptor that wraps methods with hooks and retry support.

    Retrieves hook configuration from the instance (_retry_config, _pre_hooks, etc.)
    and executes the method with stamina.retry_context.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        context_factory: Callable[..., Any] | None = None,
        retry_config: RetryConfig | None = None,
        hooks: Hooks | None = None,
    ) -> None:
        self.func = func
        self.context_factory = context_factory
        if retry_config is not None and hooks is not None:
            raise ValueError("Cannot specify both retry_config and hooks")
        self.retry_config = retry_config
        self.hooks = hooks
        # Copy metadata from the wrapped function
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__
        self.__module__ = func.__module__
        self.__qualname__ = func.__qualname__
        self.__annotations__ = func.__annotations__

    def _create_wrapper(
        self,
        hooks: Hooks,
        context: Any,
        callable_name: str,
        prepend_args: tuple[Any, ...] = (),
    ) -> Callable[..., Any]:
        """Create wrapper function with hooks and retry support.

        Args:
            hooks: Hook configuration to use
            context: Context object for hooks
            callable_name: Name for stamina logging
            prepend_args: Arguments to prepend to function call (e.g., instance for methods)

        Returns:
            Wrapper function that executes hooks and retries
        """
        hook_args = (context,) if context is not None else ()

        @functools.wraps(self.func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retry_config = self.retry_config or hooks.retry_config or NO_RETRY_CONFIG

            # Pre-hooks (once before retry)
            for hook in hooks.pre_hooks:
                hook(*hook_args)

            try:
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
                            for retry_hook in hooks.retry_hooks:
                                retry_hook(*hook_args, attempt.num)

                        # Execute method - no yield, just return!
                        return self.func(*prepend_args, *args, **kwargs)
            except:
                # Error hooks
                for hook in hooks.error_hooks:
                    hook(*hook_args)
                raise
            finally:
                # Post hooks
                for hook in hooks.post_hooks:
                    hook(*hook_args)

        return wrapper

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Direct call - for standalone functions and static methods."""
        if self.hooks is None:
            raise ValueError(
                "Cannot call decorated function directly without hooks parameter. "
                "Use @invoke_with_hooks(hooks=Hooks(...)) or call as instance method."
            )

        # Create context without instance
        context = self.context_factory() if self.context_factory else None
        callable_name = self.func.__name__

        # Create and execute wrapper
        wrapper = self._create_wrapper(
            hooks=self.hooks,
            context=context,
            callable_name=callable_name,
            prepend_args=(),
        )
        return wrapper(*args, **kwargs)

    def __get__(self, instance: Any, _owner: type | None = None) -> Any:
        """Descriptor protocol - binds method to instance."""
        if instance is None:
            return self

        # Get hook config from instance (or use override from decorator)
        hooks: Hooks = self.hooks or getattr(instance, "_hooks", Hooks()) or Hooks()

        # Create context (only pass instance to context_factory)
        context = self.context_factory(instance) if self.context_factory else None
        prepend_args: tuple[Any, ...] = ()

        # Determine callable name and prepend args
        if isinstance(instance, _ExecutionWrapper):
            # executed via Hooks.invoke()
            callable_name = self.func.__name__
        else:
            callable_name = f"{instance.__class__.__name__}.{self.func.__name__}"
            # add instance (self) as first argument for class instance method calls
            prepend_args = (instance,)

        # Create and return wrapper
        return self._create_wrapper(
            hooks=hooks,
            context=context,
            callable_name=callable_name,
            prepend_args=prepend_args,
        )
