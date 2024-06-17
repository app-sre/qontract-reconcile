import json
from collections.abc import (
    Iterable,
    Mapping,
)

import yaml
from tabulate import tabulate


def print_output(
    options: Mapping[str, str | bool],
    content: list[dict],
    columns: Iterable[str] = (),
) -> str | None:
    if options["sort"]:
        content.sort(key=lambda c: tuple(c.values()))
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
        formatted_content = format_table(content, columns, table_format="github")
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


def format_table(content, columns, table_format="simple") -> str:
    headers = [column.upper() for column in columns]
    table_data = []
    for item in content:
        row_data = []
        for column in columns:
            # example: for column 'cluster.name'
            # cell = item['cluster']['name']
            cell = item
            for token in column.split("."):
                cell = cell.get(token) or {}
            if cell == {}:
                cell = ""
            if isinstance(cell, list):
                if table_format == "github":
                    cell = "<br />".join(cell)
                else:
                    cell = "\n".join(cell)
            if table_format == "github" and isinstance(cell, str):
                cell = cell.replace("|", "&#124;")
            row_data.append(cell)
        table_data.append(row_data)
    return tabulate(table_data, headers=headers, tablefmt=table_format)
