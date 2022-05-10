import os
import requests

from graphql import build_client_schema, get_introspection_query

from query_parser import ParsedObject, QueryParser


SPACES = "    "


def query_schema() -> dict:
    query = get_introspection_query()
    request = requests.post("http://localhost:4000/graphql", json={"query": query})
    if request.status_code == 200:
        return request.json()["data"]


def find_query_files() -> list[str]:
    return [file for file in os.listdir("code_gen/gql_queries") if file.endswith(".gql")]


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
        if is_primitive(typ):
            continue

        lines.append("\n")
        lines.append("\n")
        lines.append(
            f"class {typ}(BaseModel):\n"
        )
        for subfield in field.child.fields:
            lines.append(f"{SPACES}{subfield.py_name}: {subfield.type} = Field(..., alias=\"{subfield.gql_name}\")\n")


def process_query(query: str, out_file: str):
    lines: list[str] = []
    query_root = query_parser.parse(query=query)
    query_data = query_root.objects[0].children[0]
    lines.append("from typing import Any\n")
    lines.append("\n")
    lines.append("from pydantic import BaseModel, Field\n")

    post_order_traverse(node=query_data, lines=lines)

    lines.append("\n")
    lines.append("\n")
    lines.append(
        f"def data_to_obj(data: dict[Any, Any]) -> {query_data.fields[0].type}:\n"
    )
    if query_data.fields[0].is_list:
        lines.append(f'{SPACES}return [{query_data.fields[0].unwrapped_type}(**el) for el in data[\"{query_data.fields[0].gql_name}\"]]\n')
    else:
        lines.append(f'{SPACES}return {query_data.fields[0].unwrapped_type}(**data[\"{query_data.fields[0].gql_name}\"])\n')
    with open(out_file, "w") as f:
        f.writelines(lines)


schema = query_schema()
query_parser = QueryParser(build_client_schema(schema))

for file in find_query_files():
    with open(f"code_gen/gql_queries/{file}", "r") as f:
        process_query(query=f.read(), out_file=f"code_gen/gen/{file[:-3]}py")
