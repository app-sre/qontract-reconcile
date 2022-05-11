import re


def _keyword_sanitizer(s: str) -> str:
    if s in ("global", "from", "type", "id", "to", "format"):
        return f"_{s}"
    return s


def primitive_to_python(name: str) -> str:
    mapping = {
        "ID": "str",
        "String": "str",
        "Int": "int",
        "Float": "float",
        "Boolean": "bool",
        "DateTime": "DateTime",
        "JSON": "Json",
    }
    return mapping.get(name, name)


def class_to_python(name: str) -> str:
    if name[-1] == "1":
        return name.replace("_v1", "V1")
    else:
        return name.replace("_v2", "V2")


def field_to_python(name: str) -> str:
    parts = re.split("(?=[A-Z])", name)
    for i, el in enumerate(parts):
        parts[i] = el.lower()

    return _keyword_sanitizer("_".join(parts))
