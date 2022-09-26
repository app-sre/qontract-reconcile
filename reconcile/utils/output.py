from typing import Iterable, Mapping, Union
from tabulate import tabulate
import json
import yaml


def print_output(
    options: Mapping[str, Union[str, bool]],
    content: list[dict],
    columns: Iterable[str] = (),
):
    if options["sort"]:
        content.sort(key=lambda c: tuple(c.values()))
    if options.get("to_string"):
        for c in content:
            for k, v in c.items():
                c[k] = str(v)

    output = options["output"]

    if output == "table":
        print_table(content, columns)
    elif output == "md":
        print_table(content, columns, table_format="github")
    elif output == "json":
        print(json.dumps(content))
    elif output == "yaml":
        print(yaml.dump(content))
    else:
        pass  # error


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
            row_data.append(cell)
        table_data.append(row_data)
    return tabulate(table_data, headers=headers, tablefmt=table_format)


def print_table(content, columns, table_format="simple"):
    print(format_table(content, columns, table_format))
