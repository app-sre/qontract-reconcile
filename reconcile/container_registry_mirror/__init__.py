from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reconcile.container_registry_mirror.protocol import (
        ContainerRegistryMirror,
    )

# The factory return type is Any at runtime to avoid a circular import
# with protocol.py. Type checkers see the Protocol via the TYPE_CHECKING
# import above.
MirrorFactory = Callable[[], Any]

# Module-level registry mapping implementation names to factory functions.
# Equivalent of Go's var Webhooks = RegisteredWebhooks{} in register.go.
_registry: dict[str, MirrorFactory] = {}


def register(name: str, factory: MirrorFactory) -> None:
    """Register a mirror implementation by name. Each implementation
    module calls this at import time, equivalent to Go's init()."""
    _registry[name] = factory


def get_mirror(name: str) -> ContainerRegistryMirror:
    """Retrieve and instantiate a registered mirror by name. Raises
    KeyError if the name was never registered, surfacing
    misconfiguration immediately."""
    return _registry[name]()


def registered_mirrors() -> dict[str, MirrorFactory]:
    """Return a copy of all registered implementations. The copy
    prevents callers from mutating the internal registry."""
    return dict(_registry)
