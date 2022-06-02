import os
import requests

from graphql import build_client_schema, get_introspection_query

from code_generator.query_parser import ParsedNode, ParsedInlineFragmentNode, QueryParser  # type: ignore


HEADER = '"""\nTHIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!\n"""\n'


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


def traverse(node: ParsedNode) -> str:
    """
    Pydantic doesnt play well with from __future__ import annotations
    --> order of class declaration is important:
    - post-order for non-inline fragment nodes, i.e., non-interface nodes
    - pre-order for nodes that implement an interface
    """
    result = ""
    for child in node.fields:
        if not isinstance(child, ParsedInlineFragmentNode):
            result = f"{result}{traverse(child)}"

    result = f"{result}{node.class_code_string()}"

    for child in node.fields:
        if isinstance(child, ParsedInlineFragmentNode):
            result = f"{result}{traverse(child)}"
    return result


def main():
    schema_raw = query_schema()
    schema = build_client_schema(schema_raw)  # type: ignore
    query_parser = QueryParser(schema=schema)
    for file in find_query_files():
        with open(file, "r") as f:
            result = query_parser.parse(f.read())
            code = traverse(result)
            with open(f"{file[:-3]}py", "w") as out_file:
                out_file.write(HEADER)
                out_file.write(
                    "from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611\n\n"
                )
                out_file.write(
                    "from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611"
                )
                out_file.write(code)
                out_file.write("\n")


main()
