from ruamel import yaml


def create_ruaml_instance(
    preserve_quotes: bool = True,
    explicit_start: bool = False,
    width: int = 4096,
    pure: bool = False,
) -> yaml.YAML:
    ruaml_instance = yaml.YAML(pure=pure)

    ruaml_instance.preserve_quotes = preserve_quotes
    ruaml_instance.explicit_start = explicit_start
    ruaml_instance.width = width

    return ruaml_instance
