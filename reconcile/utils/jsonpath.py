from itertools import zip_longest
from typing import Optional

import jsonpath_ng
import jsonpath_ng.ext.filter


def narrow_jsonpath_node(
    path_1: jsonpath_ng.JSONPath, path_2: jsonpath_ng.JSONPath
) -> jsonpath_ng.JSONPath:
    """
    given two jsonpath nodes, return the most specific and narrow one
    e.g. an index is more specific than a slice, a filter is more specific than
    a slice, etc.

    if the two nodes are not compatible, return None. e.g. a filter and an index
    might cover different sets of data, so not compatible
    """
    if path_1 == path_2:
        return path_1
    elif isinstance(path_1, jsonpath_ng.Fields) and isinstance(
        path_2, jsonpath_ng.Fields
    ):
        if path_1.fields == ("*",):
            return path_2
        elif path_2.fields == ("*",):
            return path_1
    elif isinstance(path_1, jsonpath_ng.Index) and isinstance(
        path_2, (jsonpath_ng.Slice, jsonpath_ng.ext.filter.Filter)
    ):
        return path_1
    elif isinstance(
        path_1, (jsonpath_ng.Slice, jsonpath_ng.ext.filter.Filter)
    ) and isinstance(path_2, jsonpath_ng.Index):
        return path_2
    elif isinstance(path_1, jsonpath_ng.ext.filter.Filter) and isinstance(
        path_2, jsonpath_ng.Slice
    ):
        return path_1
    elif isinstance(path_1, jsonpath_ng.Slice) and isinstance(
        path_2, jsonpath_ng.ext.filter.Filter
    ):
        return path_2

    return None


def jsonpath_parts(
    path: jsonpath_ng.JSONPath, ignore_filter: Optional[bool] = False
) -> list[jsonpath_ng.JSONPath]:
    """
    Return a list of JSONPath nodes that make up the given path.
    """
    parts: list[jsonpath_ng.JSONPath] = []
    while isinstance(path, jsonpath_ng.Child):
        current = path.right
        path = path.left
        if isinstance(current, jsonpath_ng.ext.filter.Filter) and ignore_filter:
            continue
        parts.insert(0, current)
    parts.insert(0, path)
    return parts


def apply_constraint_to_path(
    path: jsonpath_ng.JSONPath,
    path_constraint: jsonpath_ng.JSONPath,
    min_common_prefix_length: int = 1,
) -> Optional[jsonpath_ng.JSONPath]:
    """
    Narrow the `path` with a more specific `path_constraint`.
    e.g. if the path constraints a slice `[*]` and the constraints a
    specific index `[0]`, the `path` will be narrowed down to `[0]`.
    """
    prefix_path = jsonpath_ng.Root()
    common = True
    common_prefix_length = 0
    for p1, p2 in zip_longest(
        jsonpath_parts(path_constraint),
        jsonpath_parts(path),
    ):
        if common and (n := narrow_jsonpath_node(p1, p2)):
            prefix_path = prefix_path.child(n)
            common_prefix_length += 1
        else:
            common = False
            if p2:
                prefix_path = prefix_path.child(p2)
            else:
                break
    if common_prefix_length < min_common_prefix_length:
        return None
    else:
        return prefix_path
