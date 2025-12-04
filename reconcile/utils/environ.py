import os
from collections.abc import Callable, Iterable
from functools import wraps
from typing import Any


def used_for_security_is_enabled() -> bool:
    used_for_security_env = os.getenv("USED_FOR_SECURITY", "false")
    return used_for_security_env.lower() == "true"


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
