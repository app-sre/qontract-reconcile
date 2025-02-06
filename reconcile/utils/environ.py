import os
from collections.abc import Callable, Iterable
from functools import wraps
from typing import Any


def environ(variables: Iterable[str] | None = None) -> Callable:
    """Check that environment variables are set before execution."""
    if variables is None:
        variables = []

    def deco_environ(f: Callable) -> Callable:
        @wraps(f)
        def f_environ(*args: Any, **kwargs: Any) -> None:
            for e in variables:
                if not os.environ.get(e):
                    raise KeyError(f"Could not find environment variable: {e}")
            f(*args, **kwargs)

        return f_environ

    return deco_environ
