from collections.abc import Callable
from contextlib import ExitStack
from functools import wraps
from typing import Any


def defer(func: Callable) -> Callable:
    """Defer code execution until the surrounding function returns.
    Useful for registering cleanup work.
    """

    @wraps(func)
    def func_wrapper(*args: Any, **kwargs: Any) -> Any:
        with ExitStack() as stack:
            return func(*args, defer=stack.callback, **kwargs)

    return func_wrapper
