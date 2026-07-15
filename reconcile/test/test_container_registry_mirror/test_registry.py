import pytest

from reconcile.container_registry_mirror import (
    get_mirror,
    register,
    registered_mirrors,
)


class TestRegisterAndRetrieve:
    """A registered implementation should be retrievable by name,
    and the factory should produce fresh instances on each call."""

    def setup_method(self) -> None:
        # Each test needs a clean registry to avoid cross-test pollution.
        # Import the module-level dict and clear it directly.
        from reconcile.container_registry_mirror import _registry

        self._original = dict(_registry)
        _registry.clear()

    def teardown_method(self) -> None:
        from reconcile.container_registry_mirror import _registry

        _registry.clear()
        _registry.update(self._original)

    def test_register_and_get_produces_instance(self) -> None:
        """Registering a factory by name, then retrieving it, should
        call the factory and return the result."""

        class FakeMirror:
            pass

        register("fake", FakeMirror)
        result = get_mirror("fake")
        assert isinstance(result, FakeMirror)

    def test_get_unregistered_name_raises_key_error(self) -> None:
        """Retrieving a name that was never registered should raise
        KeyError, surfacing the misconfiguration immediately."""
        with pytest.raises(KeyError):
            get_mirror("nonexistent")

    def test_register_same_name_overwrites(self) -> None:
        """Registering the same name twice should overwrite the first
        factory, matching Go's map-assignment semantics."""

        class First:
            pass

        class Second:
            pass

        register("mirror", First)
        register("mirror", Second)
        result = get_mirror("mirror")
        assert isinstance(result, Second)

    def test_registered_mirrors_returns_all(self) -> None:
        """registered_mirrors() should return a dict of all registered
        name-to-factory mappings."""

        class Alpha:
            pass

        class Beta:
            pass

        register("alpha", Alpha)
        register("beta", Beta)

        mirrors = registered_mirrors()
        assert "alpha" in mirrors
        assert "beta" in mirrors
        assert len(mirrors) == 2

    def test_registered_mirrors_returns_copy(self) -> None:
        """Mutating the returned dict should not affect the internal
        registry, preventing accidental corruption."""

        class Gamma:
            pass

        register("gamma", Gamma)
        mirrors = registered_mirrors()
        mirrors.clear()

        # The internal registry should still have the entry.
        result = get_mirror("gamma")
        assert isinstance(result, Gamma)

    def test_get_mirror_calls_factory_each_time(self) -> None:
        """Each call to get_mirror should invoke the factory, producing
        a new instance rather than returning a cached one."""
        call_count = 0

        class Counted:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

        register("counted", Counted)
        get_mirror("counted")
        get_mirror("counted")
        assert call_count == 2
