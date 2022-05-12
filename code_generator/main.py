import os
import requests

from graphql import build_client_schema, get_introspection_query

from code_generator.query_parser import ParsedObject, QueryParser  # type: ignore


HEADER = '"""\nTHIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!\n"""\n'
SPACES = "    "


def query_schema() -> dict:
    gql_url = "http://localhost:4000/graphql"
    query = get_introspection_query()
    request = requests.post(gql_url, json={"query": query})
    if request.status_code == 200:
        return request.json()["data"]
    raise Exception(f"Could not query {gql_url}")


def find_query_files() -> list[str]:
    result: list[str] = []
    for root, _, files in os.walk("reconcile/gql_queries"):
        for name in files:
            if name.endswith(".gql"):
                result.append(os.path.join(root, name))
    return result


def is_primitive(name: str) -> bool:
    return name in ("int", "str", "bool", "float", "DateTime")


def post_order_traverse(node: ParsedObject, lines: list[str]):
    """
    Pydantic doesnt play well with from __future__ import annotations
    --> order of class declaration is important --> post-order
    """
    for child in node.children:
        post_order_traverse(node=child, lines=lines)

    for field in node.fields:
        typ = field.unwrapped_type
        if is_primitive(typ) or not field.child:
            continue

        lines.append("\n")
        lines.append("\n")
        lines.append(f"class {typ}(BaseModel):\n")
        for subfield in field.child.fields:
            if subfield.nullable:
                lines.append(
                    f'{SPACES}{subfield.py_name}: Optional[{subfield.type}] = Field(..., alias="{subfield.gql_name}")\n'
                )
            else:
                lines.append(
                    f'{SPACES}{subfield.py_name}: {subfield.type} = Field(..., alias="{subfield.gql_name}")\n'
                )


def process_query(query_parser: QueryParser, query: str, out_file: str):
    lines: list[str] = []
    query_root = query_parser.parse(query=query)
    query_data = query_root.objects[0].children[0]
    lines.append(f"{HEADER}\n")
    lines.append(
        "from typing import Any, Optional  # noqa: F401 # pylint: disable=W0611\n"
    )
    lines.append("\n")
    lines.append(
        "from pydantic import BaseModel, Field, Json  # noqa: F401  # pylint: disable=W0611\n"
    )

    post_order_traverse(node=query_data, lines=lines)

    lines.append("\n")
    lines.append("\n")
    lines.append(
        f"def data_to_obj(data: dict[Any, Any]) -> {query_data.fields[0].type}:\n"
    )
    if query_data.fields[0].is_list:
        lines.append(
            f'{SPACES}return [{query_data.fields[0].unwrapped_type}(**el) for el in data["{query_data.fields[0].gql_name}"]]\n'
        )
    else:
        lines.append(
            f'{SPACES}return {query_data.fields[0].unwrapped_type}(**data["{query_data.fields[0].gql_name}"])\n'
        )
    with open(out_file, "w") as f:
        f.writelines(lines)


def main():
    schema_raw = query_schema()
    schema = build_client_schema(schema_raw)  # type: ignore
    query_parser = QueryParser(schema)

    for file in find_query_files():
        with open(file, "r") as f:
            process_query(
                query_parser=query_parser,
                query=f.read(),
                out_file=f"{file[:-3]}py",
            )
