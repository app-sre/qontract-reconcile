"""Tests for ruamel YAML utilities."""

from qontract_utils.ruamel import create_ruamel_instance, dump_yaml


def test_create_ruamel_instance_defaults() -> None:
    """Test create_ruamel_instance with default settings."""
    yaml = create_ruamel_instance()

    assert yaml.preserve_quotes is True
    assert yaml.explicit_start is False
    assert yaml.width == 4096


def test_create_ruamel_instance_explicit_start() -> None:
    """Test create_ruamel_instance with explicit_start=True."""
    yaml = create_ruamel_instance(explicit_start=True)

    assert yaml.explicit_start is True


def test_create_ruamel_instance_custom_width() -> None:
    """Test create_ruamel_instance with custom width."""
    yaml = create_ruamel_instance(width=80)

    assert yaml.width == 80


def test_create_ruamel_instance_no_preserve_quotes() -> None:
    """Test create_ruamel_instance with preserve_quotes=False."""
    yaml = create_ruamel_instance(preserve_quotes=False)

    assert yaml.preserve_quotes is False


def test_dump_yaml() -> None:
    """Test dump_yaml serializes content to string."""
    yaml = create_ruamel_instance(explicit_start=True)
    content = yaml.load("name: alice\nage: 30\n")

    result = dump_yaml(yaml, content)

    assert "name: alice" in result
    assert "age: 30" in result


def test_dump_yaml_preserves_structure() -> None:
    """Test dump_yaml preserves YAML structure with lists."""
    yaml = create_ruamel_instance(explicit_start=True)
    content = {"users": ["alice", "bob"], "count": 2}

    result = dump_yaml(yaml, content)

    assert "users:" in result
    assert "- alice" in result
    assert "- bob" in result
    assert "count: 2" in result


def test_dump_yaml_explicit_start() -> None:
    """Test dump_yaml includes --- when explicit_start is True."""
    yaml = create_ruamel_instance(explicit_start=True)
    content = {"key": "value"}

    result = dump_yaml(yaml, content)

    assert result.startswith("---")


def test_dump_yaml_roundtrip() -> None:
    """Test dump_yaml produces content that can be loaded back."""
    yaml = create_ruamel_instance(explicit_start=True)
    original = {"users": [{"name": "alice"}, {"name": "bob"}], "count": 2}

    dumped = dump_yaml(yaml, original)
    loaded = yaml.load(dumped)

    assert loaded["users"][0]["name"] == "alice"
    assert loaded["users"][1]["name"] == "bob"
    assert loaded["count"] == 2
