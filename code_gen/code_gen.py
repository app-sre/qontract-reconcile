import os
import requests
from typing import Optional

from graphql import build_client_schema, get_introspection_query

from query_parser import ParsedField, ParsedObject, QueryParser
import mapper


SPACES = "    "


def query_schema() -> dict:
    query = get_introspection_query()
    request = requests.post("http://localhost:4000/graphql", json={"query": query})
    if request.status_code == 200:
        return request.json()["data"]


schema = query_schema()

#######################
# SCHEMA PARSER START
#######################


def parse_field_type(m: Optional[dict]) -> str:
    if not m:
        return ""

    kind = m["kind"]
    name = m["name"] or ""
    if kind == "SCALAR":
        name = mapper.primitive_to_python(name)
    if kind in ("OBJECT", "INTERFACE"):
        name = mapper.class_to_python(name)
    sub = parse_field_type(m["ofType"]) or ""

    if kind == "LIST":
        return f"list[{name}{sub}]"
    return f"{name}{sub}"


def write_schema_file(schema: dict, out_file: str):
    schema = query_schema()

    lines = []
    types = schema["__schema"]["types"]

    lines.append("# pylint: disable=too-many-lines\n")
    lines.append("# pylint: disable=too-many-instance-attributes\n")
    lines.append("from __future__ import annotations\n")
    lines.append("from dataclasses import dataclass\n")
    lines.append("from typing import Optional\n")

    for t in types:
        if not t["kind"] in ("OBJECT", "INTERFACE"):
            continue

        if t["name"].startswith("__"):
            continue

        name = mapper.class_to_python(t["name"])
        lines.append("\n")
        lines.append("\n")
        lines.append("@dataclass\n")
        lines.append(f"class {name}:\n")
        for field in t["fields"]:
            field_name = mapper.field_to_python(field["name"])
            field_type = parse_field_type(field["type"])
            lines.append(f"{SPACES}{field_name}: Optional[{field_type}] = None\n")

    with open(out_file, "w") as f:
        f.writelines(lines)


write_schema_file(schema=schema, out_file="code_gen/gen/schema.py")

#######################
# QUERY PARSER START
#######################


def find_query_files() -> list[str]:
    return [file for file in os.listdir("code_gen/gql_queries") if file.endswith(".gql")]


def is_primitive(name: str) -> bool:
    return name in ("int", "str", "bool", "float", "DateTime")


def unwrap_list(field: ParsedField, prefix: str, lines: list[str]):
    if not field.type.startswith("list["):
        return
    lines.append("\n")
    lines.append("\n")
    lines.append(
        f"def {prefix}_list_{field.py_name}(data: list[dict[Any, Any]]) -> {field.type}:\n"
    )
    lines.append(f"{SPACES}result: {field.type} = []\n")
    lines.append(f"{SPACES}for el in data:\n")
    lines.append(f"{SPACES}{SPACES}result.append({prefix}_{field.py_name}(el))\n")
    lines.append(f"{SPACES}return result\n")


def traverse(node: ParsedObject, prefix: str, lines: list[str]):
    for field in node.fields:
        typ = field.unwrapped_type
        unwrap_list(field=field, prefix=prefix, lines=lines)
        lines.append("\n")
        lines.append("\n")
        if is_primitive(typ):
            lines.append(f"def {prefix}_{field.py_name}(data: str) -> {typ}:\n")
            lines.append(f"{SPACES}return {typ}(data)\n")
        else:
            lines.append(
                f"def {prefix}_{field.py_name}(data: dict[Any, Any]) -> {typ}:\n"
            )
            lines.append(f"{SPACES}result: {typ} = {typ}()\n")
            for subfield in field.child.fields:
                pp = "list_" if subfield.is_list else ""
                lines.append(
                    f'{SPACES}result.{subfield.py_name} = {prefix}_{node.py_name}_{pp}{subfield.py_name}(data=data["{subfield.gql_name}"])\n'
                )
            lines.append(f"{SPACES}return result\n")
    for child in node.children:
        traverse(node=child, prefix=f"{prefix}_{node.py_name}", lines=lines)


query_parser = QueryParser(build_client_schema(schema))


def process_query(query: str, out_file: str):
    lines: list[str] = []
    query_root = query_parser.parse(query=query)
    query_data = query_root.objects[0].children[0]
    lines.append("from typing import Any\n")
    lines.append("\n")
    lines.append("from code_gen.gen.schema import *\n")
    lines.append("\n")
    lines.append("\n")
    lines.append(
        f"def data_to_obj(data: dict[Any, Any]) -> {query_data.fields[0].type}:\n"
    )
    data_name = query_data.fields[0].gql_name
    if query_data.fields[0].is_list:
        data_name = f"list_{data_name}"
    lines.append(
        f'{SPACES}result: {query_data.fields[0].type} = _{data_name}(data=data["{query_data.fields[0].gql_name}"])\n'
    )
    lines.append(f"{SPACES}return result\n")
    traverse(node=query_data, prefix="", lines=lines)
    with open(out_file, "w") as f:
        f.writelines(lines)


for file in find_query_files():
    with open(f"code_gen/gql_queries/{file}", "r") as f:
        process_query(query=f.read(), out_file=f"code_gen/gen/{file[:-3]}py")
