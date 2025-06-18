import json
import re
from collections.abc import Iterable, Mapping

import yaml
from tabulate import tabulate


def print_output(
    options: Mapping[str, str | bool],
    content: Iterable[dict],
    columns: Iterable[str] = (),
) -> str | None:
    if options["sort"]:
        content = sorted(content, key=lambda c: tuple(c.values()))
    if options.get("to_string"):
        for c in content:
            for k, v in c.items():
                c[k] = str(v)

    output = options["output"]

    formatted_content = None
    if output == "table":
        formatted_content = format_table(content, columns)
        print(formatted_content)
    elif output == "md":
        formatted_content = re.sub(
            r" +", " ", format_table(content, columns, table_format="github")
        )
        print(formatted_content)
    elif output == "json":
        formatted_content = json.dumps(content)
        print(formatted_content)
    elif output == "yaml":
        formatted_content = yaml.dump(content)
        print(formatted_content)
    else:
        pass  # error

    return formatted_content


def _format_cell(cell: dict, column: str, table_format: str) -> dict | str:
    # example: for column 'cluster.name'
    # cell = item['cluster']['name']
    raw_data = cell
    for token in column.split("."):
        raw_data = raw_data.get(token) or {}
    if raw_data == {}:
        return ""

    if not isinstance(raw_data, list | str):
        return raw_data

    data = ""
    if isinstance(raw_data, str):
        data = raw_data

    if isinstance(raw_data, list):
        if table_format == "github":
            data = "<br />".join(raw_data)
        else:
            data = "\n".join(raw_data)

    if table_format == "github":
        return data.replace("|", "&#124;")

    return data


def format_table(
    content: Iterable[dict], columns: Iterable[str], table_format: str = "simple"
) -> str:
    headers = [column.upper() for column in columns]
    table_data = []
    for item in content:
        row_data = [_format_cell(item, column, table_format) for column in columns]
        table_data.append(row_data)
    return tabulate(table_data, headers=headers, tablefmt=table_format)
