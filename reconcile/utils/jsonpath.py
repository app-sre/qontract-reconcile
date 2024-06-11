import logging
from functools import (
    lru_cache,
    reduce,
)
from itertools import zip_longest

import jsonpath_ng
import jsonpath_ng.ext.filter


@lru_cache(maxsize=256)
def parse_jsonpath(jsonpath_expression: str) -> jsonpath_ng.JSONPath:
    """
    parses a JSONPath expression and returns a JSONPath object.
    """
    contains_filter = "?" in jsonpath_expression
    if not contains_filter:
        try:
            # the regular parser is faster, but does not support filters
            # we will success in this branch most of the time
            return jsonpath_ng.parse(jsonpath_expression)
        except Exception:
            # something we did not cover in our prechecks prevented the use of the
            # regular parser. we will try the extended parser, which supports filters
            # and more
            logging.warning(
                f"Unable to parse '{jsonpath_expression}' with the regular parser"
            )

    return jsonpath_ng.ext.parse(jsonpath_expression)


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

    if isinstance(path_1, jsonpath_ng.Fields) and isinstance(
        path_2, jsonpath_ng.Fields
    ):
        if path_1.fields == ("*",):
            return path_2
        if path_2.fields == ("*",):
            return path_1
    elif isinstance(path_1, jsonpath_ng.Index) and isinstance(
        path_2, jsonpath_ng.Slice | jsonpath_ng.ext.filter.Filter
    ):
        return path_1
    elif isinstance(
        path_1, jsonpath_ng.Slice | jsonpath_ng.ext.filter.Filter
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


def sortable_jsonpath_string_repr(
    path: jsonpath_ng.JSONPath, index_padding: int = 5
) -> str:
    """
    Return a string representation of the JSONPath that can be used for sorting.
    The relevant aspect is the representation of an Index, which needs to be left
    padded with zeros to ensure comparability of the string representation.

    Please be aware that the resulting string representation is not necessarily
    a valid JSONPath expression, even though it might look like one occasionally.
    The only purpose of this function is to produce sortable strings.
    """
    sortable_parts = []
    for p in jsonpath_parts(path, ignore_filter=True):
        if isinstance(p, jsonpath_ng.Fields):
            sortable_parts.append(p.fields[0])
        elif isinstance(p, jsonpath_ng.Index):
            sortable_parts.append(f"[{str(p.index).zfill(index_padding)}]")
        elif isinstance(p, jsonpath_ng.Slice):
            sortable_parts.append("*")
    return ".".join(sortable_parts)


def jsonpath_parts(
    path: jsonpath_ng.JSONPath, ignore_filter: bool = False, ignore_root: bool = False
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
    if isinstance(path, jsonpath_ng.Root) and ignore_root:
        return parts
    parts.insert(0, path)
    return parts


def apply_constraint_to_path(
    path: jsonpath_ng.JSONPath,
    path_constraint: jsonpath_ng.JSONPath,
    min_common_prefix_length: int = 1,
) -> jsonpath_ng.JSONPath | None:
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
    return prefix_path


def remove_prefix_from_path(
    path: jsonpath_ng.JSONPath, prefix: jsonpath_ng.JSONPath
) -> jsonpath_ng.JSONPath | None:
    path_parts = jsonpath_parts(path, ignore_root=True)
    prefix_parts = jsonpath_parts(prefix, ignore_root=True)

    if len(path_parts) < len(prefix_parts):
        return None

    # check that the path is properly prefixed
    for i, p in enumerate(prefix_parts):
        if p != path_parts[i]:
            return None

    suffix = path_parts[len(prefix_parts) :]
    if suffix:
        return reduce(lambda a, b: a.child(b), suffix)
    return None
