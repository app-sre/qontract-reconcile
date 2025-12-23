import contextlib
from collections.abc import Callable, Generator
from typing import Any


@contextlib.contextmanager
def invoke_with_hooks[T](
    context: T,
    pre_hooks: list[Callable[[T], None]] | None = None,
    post_hooks: list[Callable[[T], None]] | None = None,
    error_hooks: list[Callable[[T], None]] | None = None,
) -> Generator[None, Any, None]:
    for hook in pre_hooks or []:
        hook(context)
    try:
        yield
    except:
        for hook in error_hooks or []:
            hook(context)
        raise
    finally:
        for hook in post_hooks or []:
            hook(context)
