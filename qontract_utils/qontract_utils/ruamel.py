from io import StringIO
from typing import Any

from ruamel.yaml.scalarstring import PreservedScalarString

from ruamel import yaml

__all__ = [
    "PreservedScalarString",
    "create_ruamel_instance",
    "dump_yaml",
    "yaml",
]


def create_ruamel_instance(
    *,
    preserve_quotes: bool = True,
    explicit_start: bool = False,
    width: int = 4096,
    pure: bool = False,
    typ: str = "rt",
) -> yaml.YAML:
    """Create a configured ruamel.yaml YAML instance.

    typ defaults to "rt" (round-trip), needed by callers that read-modify-write
    YAML and must preserve comments/formatting. Pass typ="safe" when parsing
    untrusted content - "rt" does not construct arbitrary Python objects from
    tags like PyYAML's default loader does, but it also doesn't reject them,
    silently loading tagged content as plain data instead of raising.
    """
    ruamel_instance = yaml.YAML(typ=typ, pure=pure)

    ruamel_instance.preserve_quotes = preserve_quotes
    ruamel_instance.explicit_start = explicit_start
    ruamel_instance.width = width

    return ruamel_instance


def dump_yaml(instance: yaml.YAML, content: Any) -> str:
    """Dump YAML content to string using the given ruamel instance.

    Args:
        instance: Configured ruamel.yaml YAML instance
        content: YAML content to serialize

    Returns:
        YAML string
    """
    with StringIO() as stream:
        instance.dump(content, stream)
        return stream.getvalue()
