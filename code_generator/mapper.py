import re

from graphql import GraphQLOutputType


def _keyword_sanitizer(s: str) -> str:
    if s in ("global", "from", "type", "id", "to", "format"):
        return f"f_{s}"
    return s


def graphql_primitive_to_python(graphql_type: GraphQLOutputType) -> str:
    mapping = {
        "ID": "str",
        "String": "str",
        "Int": "int",
        "Float": "float",
        "Boolean": "bool",
        "DateTime": "DateTime",
        "JSON": "Json",
    }
    return mapping.get(str(graphql_type), str(graphql_type))


def graphql_field_name_to_python(name: str) -> str:
    parts = re.split("(?=[A-Z])", name)
    for i, el in enumerate(parts):
        parts[i] = el.lower()

    return _keyword_sanitizer("_".join(parts))
