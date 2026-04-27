from io import StringIO
from typing import Any

from ruamel import yaml


def create_ruamel_instance(
    *,
    preserve_quotes: bool = True,
    explicit_start: bool = False,
    width: int = 4096,
    pure: bool = False,
) -> yaml.YAML:
    ruamel_instance = yaml.YAML(pure=pure)

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
