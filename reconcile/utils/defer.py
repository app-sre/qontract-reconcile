from __future__ import annotations

from contextlib import ExitStack
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def defer(func: Callable) -> Callable:
    """Defer code execution until the surrounding function returns.
    Useful for registering cleanup work.
    """

    @wraps(func)
    def func_wrapper(*args: Any, **kwargs: Any) -> Any:
        with ExitStack() as stack:
            return func(*args, defer=stack.callback, **kwargs)

    return func_wrapper
