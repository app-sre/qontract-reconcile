from contextlib import ExitStack
from functools import wraps


def defer(func):
    """Defer code execution until the surrounding function returns.
    Useful for registering cleanup work.
    """

    @wraps(func)
    def func_wrapper(*args, **kwargs):
        with ExitStack() as stack:
            return func(*args, defer=stack.callback, **kwargs)

    return func_wrapper
